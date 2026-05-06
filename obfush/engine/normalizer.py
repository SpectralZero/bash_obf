"""
AST normaliser — canonicalises the AST for consistent transformation.

Normalisation ensures that semantically identical constructs have the
same AST structure, regardless of how they were written in the source.
"""

from __future__ import annotations

import re
import copy
from typing import Any


def normalize(ast: dict) -> dict:
    """Apply all normalisation passes to the AST.

    Passes:
        1. Unify variable references to ${var} form
        2. Canonicalise test expressions
        3. Flatten trivial list nodes
        4. Remove comments
        5. Track variable scope

    Args:
        ast: Parsed AST from ast_parser.

    Returns:
        Normalised AST (new dict, original is not mutated).
    """
    ast = copy.deepcopy(ast)
    ast = _normalize_variable_refs(ast)
    ast = _canonicalize_tests(ast)
    ast = _flatten_trivial_lists(ast)
    ast = _strip_comments(ast)
    ast = _track_scopes(ast)
    return ast


# ──────────────────────────────────────────────────────────────────────
# Pass 1: Unify variable references
# ──────────────────────────────────────────────────────────────────────

_SIMPLE_VAR_RE = re.compile(r'\$([a-zA-Z_][a-zA-Z0-9_]*)')


def _normalize_variable_refs(ast: dict) -> dict:
    """Ensure all variable references use ${var} form in metadata."""
    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        # Track variable references in word nodes
        if node.get("type") == "word":
            value = node.get("value", "")
            # Find $VAR patterns and annotate as refs
            refs = _SIMPLE_VAR_RE.findall(value)
            if refs:
                node.setdefault("var_refs", []).extend(refs)

        # Track variable references in expansions
        if node.get("type") == "expansion" and node.get("kind") == "parameter":
            var_name = node.get("value", "")
            if var_name:
                node["var_name"] = var_name

        # Recurse
        for key in ("parts", "body"):
            val = node.get(key)
            if isinstance(val, list):
                node[key] = [_walk(i) if isinstance(i, dict) else i for i in val]
            elif isinstance(val, dict):
                node[key] = _walk(val)

        return node

    return _walk(ast)


# ──────────────────────────────────────────────────────────────────────
# Pass 2: Canonicalise test expressions
# ──────────────────────────────────────────────────────────────────────

def _canonicalize_tests(ast: dict) -> dict:
    """Normalise [ ... ] and test commands to canonical test_expr nodes."""
    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        if node.get("type") == "command":
            parts = node.get("parts", [])
            if parts and parts[0].get("type") == "word":
                first_word = parts[0].get("value", "")
                if first_word in ("[", "test"):
                    # Convert to canonical test expression
                    test_parts = parts[1:]
                    # Remove trailing ] if present
                    if (test_parts and test_parts[-1].get("type") == "word"
                            and test_parts[-1].get("value") == "]"):
                        test_parts = test_parts[:-1]
                    node["type"] = "test_expr"
                    node["test_parts"] = test_parts
                    node["original_style"] = first_word

        # Handle [[ ... ]] compound commands
        if node.get("type") == "compound" and node.get("kind") == "[[":
            node["type"] = "test_expr"
            node["original_style"] = "[["

        for key in ("parts", "body", "test_parts"):
            val = node.get(key)
            if isinstance(val, list):
                node[key] = [_walk(i) if isinstance(i, dict) else i for i in val]
            elif isinstance(val, dict):
                node[key] = _walk(val)

        return node

    return _walk(ast)


# ──────────────────────────────────────────────────────────────────────
# Pass 3: Flatten trivial lists
# ──────────────────────────────────────────────────────────────────────

def _flatten_trivial_lists(ast: dict) -> dict:
    """Flatten list nodes that contain only one command."""
    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        for key in ("parts", "body"):
            val = node.get(key)
            if isinstance(val, list):
                new_list = []
                for item in val:
                    if isinstance(item, dict):
                        item = _walk(item)
                        # Flatten single-child lists
                        if (item.get("type") == "list"
                                and len(item.get("parts", [])) == 1):
                            new_list.append(item["parts"][0])
                        else:
                            new_list.append(item)
                    else:
                        new_list.append(item)
                node[key] = new_list
            elif isinstance(val, dict):
                node[key] = _walk(val)

        return node

    return _walk(ast)


# ──────────────────────────────────────────────────────────────────────
# Pass 4: Strip comments
# ──────────────────────────────────────────────────────────────────────

def _strip_comments(ast: dict) -> dict:
    """Remove comment nodes from the AST."""
    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        for key in ("parts", "body"):
            val = node.get(key)
            if isinstance(val, list):
                node[key] = [
                    _walk(i)
                    for i in val
                    if not (isinstance(i, dict) and i.get("type") == "comment")
                ]
            elif isinstance(val, dict):
                if val.get("type") != "comment":
                    node[key] = _walk(val)

        return node

    return _walk(ast)


# ──────────────────────────────────────────────────────────────────────
# Pass 5: Track variable scope
# ──────────────────────────────────────────────────────────────────────

def _track_scopes(ast: dict) -> dict:
    """Annotate AST nodes with scope information.

    Tracks which variables are:
    - local (declared with 'local' inside a function)
    - global (everything else)
    - assigned (has a value set)
    - read (referenced in a command or expansion)
    """
    scope_info: dict[str, Any] = {
        "globals": set(),
        "locals": {},  # function_name → set of local var names
        "assignments": set(),
        "reads": set(),
    }

    def _walk(node: dict, current_function: str | None = None) -> None:
        if not isinstance(node, dict):
            return

        # Track function definitions
        if node.get("type") == "function_def":
            func_name = node.get("name", "")
            scope_info["locals"].setdefault(func_name, set())
            body = node.get("body")
            if isinstance(body, dict):
                _walk(body, current_function=func_name)
            return

        # Track assignments
        if node.get("type") == "assignment":
            var_name = node.get("name", "")
            scope_info["assignments"].add(var_name)
            if current_function:
                # Check if preceded by 'local' — we approximate this
                scope_info["locals"].setdefault(current_function, set())
            else:
                scope_info["globals"].add(var_name)

        # Track local declarations
        if node.get("type") == "command":
            parts = node.get("parts", [])
            if (parts and parts[0].get("type") == "word"
                    and parts[0].get("value") == "local" and current_function):
                for part in parts[1:]:
                    if part.get("type") in ("word", "assignment"):
                        name = part.get("name") or part.get("value", "").split("=")[0]
                        scope_info["locals"][current_function].add(name)

        # Track variable reads
        for ref in node.get("var_refs", []):
            scope_info["reads"].add(ref)

        if node.get("type") == "expansion" and node.get("kind") == "parameter":
            scope_info["reads"].add(node.get("value", ""))

        # Recurse
        for key in ("parts", "body", "test_parts"):
            val = node.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk(item, current_function)
            elif isinstance(val, dict):
                _walk(val, current_function)

    _walk(ast)
    ast["_scope"] = scope_info
    return ast
