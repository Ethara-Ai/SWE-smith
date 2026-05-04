import libcst

from swesmith.bug_gen.procedural.python.base import PythonProceduralModifier
from swesmith.constants import CodeProperty


class SemanticDefaultArgMutateModifier(PythonProceduralModifier):
    explanation: str = (
        "A default argument value in the function signature may be incorrect."
    )
    name: str = "func_pm_semantic_default_arg_mutate"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_DEFAULT_ARG]
    min_complexity: int = 3

    class Transformer(PythonProceduralModifier.Transformer):
        def leave_Param(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            if updated_node.default is None:
                return updated_node
            default = updated_node.default
            if isinstance(default, libcst.Name) and default.value == "None":
                new_default = self.parent.rand.choice(
                    [
                        libcst.SimpleString(value='""'),
                        libcst.Integer(value="0"),
                        libcst.Name(value="False"),
                        libcst.List(elements=[]),
                    ]
                )
                return updated_node.with_changes(default=new_default)
            if isinstance(default, libcst.Name) and default.value == "True":
                return updated_node.with_changes(default=libcst.Name(value="False"))
            if isinstance(default, libcst.Name) and default.value == "False":
                return updated_node.with_changes(default=libcst.Name(value="True"))
            if isinstance(default, libcst.Integer):
                try:
                    val = int(default.value)
                except ValueError:
                    val = int(default.value, 16)
                new_val = val + self.parent.rand.choice([-1, 1])
                return updated_node.with_changes(
                    default=libcst.Integer(value=str(new_val))
                )
            if isinstance(
                default,
                (
                    libcst.SimpleString,
                    libcst.ConcatenatedString,
                    libcst.FormattedString,
                ),
            ):
                return updated_node.with_changes(
                    default=libcst.SimpleString(value='""')
                )
            if isinstance(default, libcst.List) and len(default.elements) == 0:
                return updated_node.with_changes(default=libcst.Name(value="None"))
            if isinstance(default, libcst.Dict) and len(default.elements) == 0:
                return updated_node.with_changes(default=libcst.Name(value="None"))
            if isinstance(default, libcst.Tuple) and len(default.elements) == 0:
                return updated_node.with_changes(default=libcst.Name(value="None"))
            return updated_node


class SemanticNoneCheckInvertModifier(PythonProceduralModifier):
    explanation: str = "A None check condition has been inverted, potentially causing null reference issues."
    name: str = "func_pm_semantic_none_check_invert"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_NONE_CHECK]
    min_complexity: int = 3

    class Transformer(PythonProceduralModifier.Transformer):
        def leave_Comparison(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            if len(updated_node.comparisons) != 1:
                return updated_node
            target = updated_node.comparisons[0]
            is_none_comparator = (
                isinstance(target.comparator, libcst.Name)
                and target.comparator.value == "None"
            )
            is_none_left = (
                isinstance(updated_node.left, libcst.Name)
                and updated_node.left.value == "None"
            )
            if not (is_none_comparator or is_none_left):
                return updated_node
            if isinstance(target.operator, libcst.Is):
                new_target = target.with_changes(operator=libcst.IsNot())
                return updated_node.with_changes(comparisons=[new_target])
            if isinstance(target.operator, libcst.IsNot):
                new_target = target.with_changes(operator=libcst.Is())
                return updated_node.with_changes(comparisons=[new_target])
            return updated_node


class SemanticEarlyReturnRemoveModifier(PythonProceduralModifier):
    explanation: str = "A guard clause (early return) has been removed, causing the function to process invalid inputs."
    name: str = "func_pm_semantic_early_return_remove"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_EARLY_RETURN]
    min_complexity: int = 4

    class Transformer(PythonProceduralModifier.Transformer):
        def _is_guard_clause(self, stmt):
            if not isinstance(stmt, libcst.SimpleStatementLine):
                if not isinstance(stmt, libcst.If):
                    return False
                node = stmt
            else:
                return False
            if node.orelse is not None:
                return False
            if not isinstance(node.body, libcst.IndentedBlock):
                return False
            for body_stmt in node.body.body:
                if isinstance(body_stmt, libcst.SimpleStatementLine):
                    for item in body_stmt.body:
                        if isinstance(item, libcst.Return):
                            return True
                        if isinstance(item, libcst.Raise):
                            return True
            return False

        def leave_FunctionDef(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            if not isinstance(updated_node.body, libcst.IndentedBlock):
                return updated_node
            body = list(updated_node.body.body)
            if len(body) <= 1:
                return updated_node
            new_body = []
            removed = False
            for i, stmt in enumerate(body):
                if i < 3 and not removed and self._is_guard_clause(stmt):
                    removed = True
                    continue
                new_body.append(stmt)
            if not removed:
                return updated_node
            return updated_node.with_changes(
                body=updated_node.body.with_changes(body=tuple(new_body))
            )


class SemanticSliceOffByOneModifier(PythonProceduralModifier):
    explanation: str = (
        "A slice boundary may be off by one, causing incorrect subsequence extraction."
    )
    name: str = "func_pm_semantic_slice_off_by_one"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_SLICE]
    min_complexity: int = 3

    class Transformer(PythonProceduralModifier.Transformer):
        def _adjust_bound(self, bound):
            if bound is None:
                return None
            if isinstance(bound, libcst.Integer):
                try:
                    val = int(bound.value)
                except ValueError:
                    val = int(bound.value, 16)
                new_val = val + self.parent.rand.choice([-1, 1])
                return libcst.Integer(value=str(new_val))
            if isinstance(bound, libcst.BinaryOperation):
                if isinstance(bound.right, libcst.Integer):
                    try:
                        val = int(bound.right.value)
                    except ValueError:
                        val = int(bound.right.value, 16)
                    new_val = val + self.parent.rand.choice([-1, 1])
                    return bound.with_changes(right=libcst.Integer(value=str(new_val)))
                return bound
            return libcst.BinaryOperation(
                left=bound,
                operator=self.parent.rand.choice([libcst.Add(), libcst.Subtract()]),
                right=libcst.Integer(value="1"),
            )

        def leave_Subscript(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            if len(updated_node.slice) != 1:
                return updated_node
            slice_elem = updated_node.slice[0]
            if not isinstance(slice_elem, libcst.SubscriptElement):
                return updated_node
            if not isinstance(slice_elem.slice, libcst.Slice):
                return updated_node
            sl = slice_elem.slice
            choice = self.parent.rand.choice(["lower", "upper"])
            if choice == "lower" and sl.lower is not None:
                new_lower = self._adjust_bound(sl.lower)
                new_slice = sl.with_changes(lower=new_lower)
            elif choice == "upper" and sl.upper is not None:
                new_upper = self._adjust_bound(sl.upper)
                new_slice = sl.with_changes(upper=new_upper)
            else:
                return updated_node
            new_elem = slice_elem.with_changes(slice=new_slice)
            return updated_node.with_changes(slice=[new_elem])


class SemanticReturnValueMutateModifier(PythonProceduralModifier):
    explanation: str = (
        "A return value has been altered, potentially changing the function's contract."
    )
    name: str = "func_pm_semantic_return_value_mutate"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_MULTIPLE_RETURN]
    min_complexity: int = 4

    class Transformer(PythonProceduralModifier.Transformer):
        def leave_Return(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            if updated_node.value is None:
                new_val = self.parent.rand.choice(
                    [
                        libcst.Integer(value="0"),
                        libcst.SimpleString(value='""'),
                    ]
                )
                return updated_node.with_changes(value=new_val)
            val = updated_node.value
            if isinstance(val, libcst.Tuple):
                elems = list(val.elements)
                if len(elems) > 1:
                    new_elems = elems[:-1]
                    if hasattr(new_elems[-1], "comma") and not isinstance(
                        new_elems[-1].comma, libcst.MaybeSentinel
                    ):
                        new_elems[-1] = new_elems[-1].with_changes(
                            comma=libcst.MaybeSentinel.DEFAULT
                        )
                    return updated_node.with_changes(
                        value=val.with_changes(elements=tuple(new_elems))
                    )
                return updated_node
            if isinstance(val, libcst.Name):
                if val.value == "True":
                    return updated_node.with_changes(value=libcst.Name(value="False"))
                if val.value == "False":
                    return updated_node.with_changes(value=libcst.Name(value="True"))
                if val.value == "None":
                    new_val = self.parent.rand.choice(
                        [
                            libcst.Integer(value="0"),
                            libcst.SimpleString(value='""'),
                        ]
                    )
                    return updated_node.with_changes(value=new_val)
                mutation = self.parent.rand.choice(["negate"])
                if mutation == "negate":
                    return updated_node.with_changes(
                        value=libcst.UnaryOperation(
                            operator=libcst.Minus(),
                            expression=val,
                        )
                    )
            if isinstance(val, libcst.Call):
                mutation = self.parent.rand.choice(["negate"])
                if mutation == "negate":
                    return updated_node.with_changes(
                        value=libcst.UnaryOperation(
                            operator=libcst.Minus(),
                            expression=val,
                        )
                    )
            return updated_node


class SemanticDictKeyMutateModifier(PythonProceduralModifier):
    explanation: str = (
        "A dictionary key may be incorrect, causing KeyError or wrong value retrieval."
    )
    name: str = "func_pm_semantic_dict_key_mutate"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_DICT_ACCESS]
    min_complexity: int = 3

    class Transformer(PythonProceduralModifier.Transformer):
        def _mutate_string_key(self, key_value):
            inner = key_value[1:-1]
            quote_char = key_value[0]
            if not inner:
                return key_value
            mutations = []
            if inner.endswith("s") and len(inner) > 1:
                mutations.append(quote_char + inner[:-1] + quote_char)
            else:
                mutations.append(quote_char + inner + "s" + quote_char)
            if inner[0].isupper():
                mutations.append(quote_char + inner[0].lower() + inner[1:] + quote_char)
            elif inner[0].islower():
                mutations.append(quote_char + inner[0].upper() + inner[1:] + quote_char)
            mutations.append(quote_char + "_" + inner + quote_char)
            return self.parent.rand.choice(mutations)

        def leave_Subscript(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            if len(updated_node.slice) != 1:
                return updated_node
            slice_elem = updated_node.slice[0]
            if not isinstance(slice_elem, libcst.SubscriptElement):
                return updated_node
            if not isinstance(slice_elem.slice, libcst.Index):
                return updated_node
            index_val = slice_elem.slice.value
            if isinstance(index_val, libcst.SimpleString):
                raw = index_val.value
                if len(raw) < 3:
                    return updated_node
                new_raw = self._mutate_string_key(raw)
                new_index = index_val.with_changes(value=new_raw)
                new_slice = slice_elem.slice.with_changes(value=new_index)
                new_elem = slice_elem.with_changes(slice=new_slice)
                return updated_node.with_changes(slice=[new_elem])
            return updated_node


class SemanticComparisonChainBreakModifier(PythonProceduralModifier):
    explanation: str = (
        "A comparison in a chained comparison has been removed or weakened."
    )
    name: str = "func_pm_semantic_comparison_chain_break"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_COMPARISON_CHAIN]
    min_complexity: int = 3

    class Transformer(PythonProceduralModifier.Transformer):
        def leave_Comparison(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            comparisons = list(updated_node.comparisons)
            if len(comparisons) < 2:
                return updated_node
            mutation = self.parent.rand.choice(["drop_last", "drop_first", "weaken"])
            if mutation == "drop_last":
                new_comparisons = comparisons[:-1]
                if hasattr(new_comparisons[-1], "comma"):
                    pass
                return updated_node.with_changes(comparisons=tuple(new_comparisons))
            if mutation == "drop_first":
                new_left = comparisons[0].comparator
                new_comparisons = comparisons[1:]
                return updated_node.with_changes(
                    left=new_left,
                    comparisons=tuple(new_comparisons),
                )
            if mutation == "weaken":
                idx = self.parent.rand.randint(0, len(comparisons) - 1)
                target = comparisons[idx]
                op = target.operator
                if isinstance(op, libcst.LessThan):
                    new_op = libcst.LessThanEqual()
                elif isinstance(op, libcst.GreaterThan):
                    new_op = libcst.GreaterThanEqual()
                elif isinstance(op, libcst.LessThanEqual):
                    new_op = libcst.LessThan()
                elif isinstance(op, libcst.GreaterThanEqual):
                    new_op = libcst.GreaterThan()
                else:
                    return updated_node
                comparisons[idx] = target.with_changes(operator=new_op)
                return updated_node.with_changes(comparisons=tuple(comparisons))
            return updated_node


class SemanticNestedCallArgSwapModifier(PythonProceduralModifier):
    explanation: str = "Arguments in a function call may be in the wrong order."
    name: str = "func_pm_semantic_nested_call_arg_swap"
    conditions: list = [CodeProperty.IS_FUNCTION, CodeProperty.HAS_FUNCTION_CALL]
    min_complexity: int = 4

    class Transformer(PythonProceduralModifier.Transformer):
        def leave_Call(self, original_node, updated_node):
            if not self.flip():
                return updated_node
            args = list(updated_node.args)
            positional_indices = [
                i
                for i, arg in enumerate(args)
                if arg.keyword is None and arg.star == ""
            ]
            if len(positional_indices) < 2:
                return updated_node
            idx_a, idx_b = self.parent.rand.sample(positional_indices, 2)
            arg_a = args[idx_a]
            arg_b = args[idx_b]
            args[idx_a] = arg_a.with_changes(value=arg_b.value)
            args[idx_b] = arg_b.with_changes(value=arg_a.value)
            return updated_node.with_changes(args=tuple(args))
