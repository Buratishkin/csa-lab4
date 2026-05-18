from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

Atom: TypeAlias = int | str
Expression: TypeAlias = Atom | list["Expression"]


class ParseError(Exception):
    pass


def tokenize(source: str) -> list[str]:
    tokens: list[str] = []
    i = 0

    while i < len(source):
        ch = source[i]

        if ch.isspace():
            i += 1
            continue

        if ch == ";":
            i = skip_comment(source, i)
            continue

        if ch in "()":
            tokens.append(ch)
            i += 1
            continue

        if ch == '"':
            token, i = read_string(source, i)
            tokens.append(token)
            continue

        token, i = read_symbol_or_number(source, i)
        tokens.append(token)

    return tokens


def skip_comment(source: str, start: int) -> int:
    i = start

    while i < len(source) and source[i] != "\n":
        i += 1

    return i


def read_string(source: str, start: int) -> tuple[str, int]:
    result = ['"']
    i = start + 1

    while i < len(source):
        ch = source[i]

        if ch == "\\":
            if i + 1 >= len(source):
                raise ParseError("Unfinished escape sequence in string literal")

            result.append(ch)
            result.append(source[i + 1])
            i += 2
            continue

        if ch == '"':
            result.append('"')
            return "".join(result), i + 1

        result.append(ch)
        i += 1

    raise ParseError("Unclosed string literal")


def read_symbol_or_number(source: str, start: int) -> tuple[str, int]:
    i = start
    result: list[str] = []

    while i < len(source):
        ch = source[i]

        if ch.isspace() or ch in "();":
            break

        result.append(ch)
        i += 1

    if not result:
        raise ParseError(f"Unexpected character: {source[start]!r}")

    return "".join(result), i


def parse(source: str) -> list[Expression]:
    return Parser(tokenize(source)).parse_program()

@dataclass
class Parser:
    tokens: list[str]
    position: int = 0

    def parse_program(self) -> list[Expression]:
        expressions: list[Expression] = []

        while not self.is_end():
            expressions.append(self.parse_expression())

        return expressions

    def parse_expression(self) -> Expression:
        if self.is_end():
            raise ParseError("Unexpected end of input")

        token = self.advance()

        if token == "(":
            return self.parse_list()

        if token == ")":
            raise ParseError("Unexpected ')'")

        return parse_atom(token)

    def parse_list(self) -> list[Expression]:
        expressions: list[Expression] = []

        while not self.is_end() and self.peek() != ")":
            expressions.append(self.parse_expression())

        if self.is_end():
            raise ParseError("Unclosed '('")

        self.expect(")")
        return expressions

    def peek(self) -> str:
        if self.is_end():
            raise ParseError("Unexpected end of input")

        return self.tokens[self.position]

    def advance(self) -> str:
        token = self.peek()
        self.position += 1
        return token

    def expect(self, expected: str) -> None:
        actual = self.advance()

        if actual != expected:
            raise ParseError(f"Expected {expected!r}, got {actual!r}")

    def is_end(self) -> bool:
        return self.position >= len(self.tokens)


def parse_atom(token: str) -> Atom:
    if is_integer_token(token):
        return int(token)

    return token


def is_integer_token(token: str) -> bool:
    if token.startswith("-"):
        return len(token) > 1 and token[1:].isdigit()

    return token.isdigit()


def is_string_literal(expression: Expression) -> bool:
    return (
        isinstance(expression, str)
        and len(expression) >= 2
        and expression[0] == '"'
        and expression[-1] == '"'
    )


def string_literal_value(expression: Expression) -> str:
    if not is_string_literal(expression):
        raise ParseError(f"Expected string literal, got: {expression!r}")

    assert isinstance(expression, str)
    return unescape_string(expression[1:-1])


def unescape_string(value: str) -> str:
    result: list[str] = []
    i = 0

    while i < len(value):
        ch = value[i]

        if ch != "\\":
            result.append(ch)
            i += 1
            continue

        if i + 1 >= len(value):
            raise ParseError("Unfinished escape sequence")

        escaped = value[i + 1]

        match escaped:
            case "n":
                result.append("\n")
            case "t":
                result.append("\t")
            case '"':
                result.append('"')
            case "\\":
                result.append("\\")
            case _:
                raise ParseError(f"Unknown escape sequence: \\{escaped}")

        i += 2

    return "".join(result)