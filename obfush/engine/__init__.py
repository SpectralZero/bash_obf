"""
obfush.engine — Core polymorphic engine components.

Submodules:
    core            PolymorphicEngine orchestrator
    seed            Seed generation & PRNG management
    layer_selector  Random layer selection with compatibility enforcement
    ast_parser      bashlex wrapper + custom fallback parser
    ast_emitter     AST → bash source code emitter
    normalizer      AST canonicalisation pass
    verifier        Sandbox equivalence tester
    entropy_evaluator  Shannon entropy & statistical analysis
"""
