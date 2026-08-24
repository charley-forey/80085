"""HTML -> Markdown. argv: input.html output.md. Writes result.json.

Covers what agents actually feed it: headings, paragraphs, links, emphasis,
inline and fenced code, ordered and unordered lists, blockquotes and rules.
script/style/head are dropped. Not a browser; a converter.
"""

import hashlib
import json
import re
import sys
from html.parser import HTMLParser


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


SKIP = {"script", "style", "head", "template"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
BLOCKS = {"p", "div", "section", "article", "main", "table", "tr"}


class Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.pre = 0
        self.lists: list[dict] = []  # {"ordered": bool, "index": int}
        self.href: str | None = None
        self.links = 0
        self.headings = 0

    # --- emission helpers ---------------------------------------------------
    def emit(self, text: str) -> None:
        self.out.append(text)

    def blankline(self) -> None:
        joined = "".join(self.out)
        if joined and not joined.endswith("\n\n"):
            self.emit("\n" if joined.endswith("\n") else "\n\n")

    # --- parser hooks -------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in HEADINGS:
            self.headings += 1
            self.blankline()
            self.emit("#" * HEADINGS[tag] + " ")
        elif tag == "pre":
            self.blankline()
            self.emit("```\n")
            self.pre += 1
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "a":
            self.href = dict(attrs).get("href")
            self.emit("[")
        elif tag in ("ul", "ol"):
            if not self.lists:
                self.blankline()
            self.lists.append({"ordered": tag == "ol", "index": 0})
        elif tag == "li":
            frame = self.lists[-1] if self.lists else {"ordered": False, "index": 0}
            frame["index"] += 1
            indent = "  " * (len(self.lists) - 1) if self.lists else ""
            marker = f"{frame['index']}." if frame["ordered"] else "-"
            joined = "".join(self.out)
            if joined and not joined.endswith("\n"):
                self.emit("\n")
            self.emit(f"{indent}{marker} ")
        elif tag == "blockquote":
            self.blankline()
            self.emit("> ")
        elif tag == "br":
            self.emit("\n")
        elif tag == "hr":
            self.blankline()
            self.emit("---")
            self.blankline()
        elif tag in BLOCKS:
            self.blankline()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in HEADINGS or tag in BLOCKS or tag == "blockquote":
            self.blankline()
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            if not "".join(self.out).endswith("\n"):
                self.emit("\n")
            self.emit("```")
            self.blankline()
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "a":
            self.links += 1
            self.emit(f"]({self.href or ''})")
            self.href = None
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            if not self.lists:
                self.blankline()
        elif tag == "li" and not "".join(self.out).endswith("\n"):
            self.emit("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.pre:
            self.emit(data)
            return
        text = " ".join(data.split())
        if not text:
            return
        # The source's own whitespace decides the spacing, so "The <b>3.2</b>
        # release" keeps its spaces and "**3.2**" stays tight to its marks.
        if data[:1].isspace():
            joined = "".join(self.out)
            if joined and not joined[-1].isspace():
                self.emit(" ")
        self.emit(text)
        if data[-1:].isspace():
            self.emit(" ")

    def markdown(self) -> str:
        text = "".join(self.out)
        # Internal runs of spaces collapse; leading indentation does not,
        # because nested list markers are indentation.
        lines = [re.sub(r"(?<=\S) {2,}", " ", line).rstrip() for line in text.split("\n")]
        text = "\n".join(lines)
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text.strip() + "\n"


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, encoding="utf-8") as handle:
        html = handle.read()
    converter = Converter()
    converter.feed(html)
    converter.close()
    with open(target, "w", encoding="utf-8", newline="\n") as out:
        out.write(converter.markdown())
    finish(
        headings=converter.headings,
        links=converter.links,
        output=target,
        sha256=digest(target),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
