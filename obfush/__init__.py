"""
obfush — Polymorphic Bash Obfuscation Engine v2.0
Author: Spectral0x00
Red Team Internal Use Only

Transforms valid bash scripts into functionally identical but statically
unrecognisable variants. Every invocation produces unique output — no two
runs yield the same code, even from identical source.

Design principle: Optimise for static anti-reverse-engineering.
Runtime detection is a separate engineering problem and is not fought here.
"""

__version__ = "2.0.0-dev"
__author__ = "Spectral0x00"
__license__ = "Proprietary"
