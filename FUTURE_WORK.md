# Future Work

## Explicitly Deferred VM Program

All virtual-machine work is deferred. The current release and documentation effort is deliberately non-VM and must not be interpreted as implementing, scheduling, or promising a VM architecture.

The following work is explicitly out of scope and deferred in full:

- VM bytecode design, encoding, serialization, validation, versioning, and compatibility.
- VM opcode definition, dispatch tables, instruction selection, lowering, and opcode polymorphism.
- A VM interpreter, execution engine, runtime, loader, verifier, debugger, or tracing model.
- A VM string pool, string interning, pooled constant format, encryption, indexing, or reconstruction.
- Junk bytecode generation, insertion, liveness, reachability, dead-instruction analysis, or junk-opcode design.
- Multi-process VM work, including splitting VM state or interpretation across processes, worker coordination, inter-process instruction dispatch, shared state, synchronization, recovery, and process topology randomization.

Existing batch worker processes, `direct-exec`, `poly-shell`, equivalence subprocesses, and the optional native loader are not VM implementations and do not reduce this deferral. Any future proposal must begin with a separate threat model, semantic model, compatibility contract, resource limits, test oracle, operational review, and explicit authorization before implementation starts.

This file tracks only the deferred VM program above. Completed non-VM release,
container, documentation, and layer API work is recorded in `CHANGELOG.md`, not
as future work.
