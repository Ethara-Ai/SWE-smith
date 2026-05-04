import re
import tree_sitter_c as tsc

from swesmith.constants import TODO_REWRITE, CodeEntity
from tree_sitter import Language, Parser, Query, QueryCursor
from swesmith.bug_gen.adapters.utils import build_entity

C_LANGUAGE = Language(tsc.language())


class CEntity(CodeEntity):
    @property
    def name(self) -> str:
        func_query = Query(
            C_LANGUAGE,
            "(function_definition (function_declarator declarator: (identifier) @name))",
        )
        func_name = self._extract_text_from_first_match(func_query, self.node, "name")
        if func_name:
            return func_name
        return ""

    @property
    def signature(self) -> str:
        body_query = Query(
            C_LANGUAGE, "(function_definition body: (compound_statement) @body)"
        )
        matches = QueryCursor(body_query).matches(self.node)
        if matches:
            body_node = matches[0][1]["body"][0]
            body_start_byte = body_node.start_byte - self.node.start_byte
            signature = self.node.text[:body_start_byte].strip().decode("utf-8")
            signature = re.sub(r"\(\s+", "(", signature).strip()
            signature = re.sub(r"\s+\)", ")", signature).strip()
            signature = re.sub(r"\s+", " ", signature).strip()
            return signature
        return ""

    @property
    def stub(self) -> str:
        return f"{self.signature} {{\n\t// {TODO_REWRITE}\n}}"

    @staticmethod
    def _extract_text_from_first_match(query, node, capture_name: str) -> str | None:
        """Extract text from tree-sitter query matches with None fallback."""
        matches = QueryCursor(query).matches(node)
        return matches[0][1][capture_name][0].text.decode("utf-8") if matches else None


def get_entities_from_file_c(
    entities: list[CEntity],
    file_path: str,
    max_entities: int = -1,
) -> None:
    """
    Parse a .c file and return up to max_entities top-level funcs and types.
    If max_entities < 0, collects them all.
    """
    parser = Parser(C_LANGUAGE)

    file_content = open(file_path, "r", encoding="utf8").read()
    tree = parser.parse(bytes(file_content, "utf8"))
    root = tree.root_node
    lines = file_content.splitlines()

    # Iterative traversal (stack-based) to avoid RecursionError on deeply
    # nested tree-sitter parse trees (common in large FFmpeg files with
    # heavy preprocessor chains or big initializer tables).
    stack = [root]
    while stack:
        if 0 <= max_entities == len(entities):
            return

        node = stack.pop()

        # not checking for error nodes here because tree-sitter-c frequently
        # generates them parsing valid pre-processor directives

        if node.type == "function_definition":
            entities.append(build_entity(node, lines, file_path, CEntity))
            if 0 <= max_entities == len(entities):
                return
            # function bodies cannot contain nested function_definitions in C,
            # so we don't need to descend further into this node.
            continue

        # push children in reverse so traversal order matches the original
        # recursive (left-to-right) walk — not strictly required but keeps
        # entity ordering stable for deterministic runs.
        stack.extend(reversed(node.children))
