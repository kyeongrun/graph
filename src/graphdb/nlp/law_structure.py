"""Step 4 준비: 법령 원문 md를 조/항/호 구조로 파싱한다.

의존관계(주어/목적어) 추출은 문장 단위가 아니라 **항(項) 단위**로 해야
한다 — 항이 이어지며 주어가 생략되는 pro-drop이 매우 흔하기 때문이다
(CLAUDE.md 4단계 메모의 예시: "①금융회사는 ...마련하여야 한다.
②제1항에도 불구하고 ...자회사등은 마련하지 아니할 수 있다"). 그래서
조문을 항 단위로 쪼개 놓아야 항간 주어 상속 규칙을 적용할 수 있다.

마크다운 구조(legalize-kr 산출물 관찰 결과):
- 조문 헤더: `##### 제N조(의M) (제목)` — "의M"은 신설조문(예: 제17조의2).
- 항 마커: `**①**`, `**②**` ... 원문자(U+2460~) 볼드. 항이 하나뿐인
  조문은 마커 없이 본문이 바로 옴 — 이때는 항번호 없는 단일 항으로 취급.
- 호(號) 목록: `  1\\. 내용` (역슬래시로 이스케이프된 마침표, 2칸 들여쓰기).
- 목(目) 목록: `    가\\. 내용` (4칸 들여쓰기, 호보다 한 단계 더 들어감).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "## 부칙"(addenda) 이후는 제1조부터 조번호가 새로 시작하는 별도 섹션
# (시행일/경과조치/다른 법률 개정 등 부수적 조항)이라 본문 조문과 구조가
# 다르고 지식그래프 대상도 아니다. 여기서 잘라내지 않으면 마지막 본문
# 조문(특히 "삭제"류 빈 조문)이 EOF까지 부칙 전체를 항 본문으로 삼켜버림.
_ADDENDA_RE = re.compile(r"^##\s*부칙\b.*$", re.MULTILINE)

_ARTICLE_HEADER_RE = re.compile(
    r"^#####\s*제(?P<num>\d+)조(?:의(?P<sub>\d+))?\s*\((?P<title>[^)]*)\)\s*$",
    re.MULTILINE,
)

# 원문자 ①~⑳(U+2460~U+2473) + ㉑~㉟(U+3251~U+325F, 21~35) — 항이 20개를
# 넘는 조문은 드물지만 방어적으로 포함.
_PARA_MARKER_RE = re.compile(r"\*\*([①-⑳㉑-㉟])\*\*\s*")
_CIRCLED_TO_INT = {chr(0x2460 + i): i + 1 for i in range(20)}
_CIRCLED_TO_INT.update({chr(0x3251 + i): i + 21 for i in range(15)})

# 호: "  1\. 내용" (2~3칸 들여쓰기), 목: "    가\. 내용" (4칸 이상 들여쓰기).
# 들여쓰기 폭으로 호/목을 구분한다 — 목이 호보다 항상 더 깊게 들어간다.
_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<label>[0-9]+|[가-힣])\\\.\s+(?P<body>.+)$",
    re.MULTILINE,
)

# "### 제2절 감사위원 <개정 2009.1.30>" 같은 장/절 헤더는 조문 헤더
# (`##### 제N조`)만큼 자주 안 나와서 별도 경계로 안 잡았는데, 그 결과
# 마지막 항의 본문에 섞여 들어간다. "<개정 .../신설 .../삭제 ...>" 개정
# 이력 주석도 실질 조문 내용이 아니라 SVO 추출에 노이즈다. 둘 다 제거.
_SECTION_HEADER_LINE_RE = re.compile(r"^#{1,4}\s+.*$", re.MULTILINE)
_REVISION_NOTE_RE = re.compile(r"<(?:개정|신설|삭제|전문개정)[^>]*>")


def _strip_noise(article_body: str) -> str:
    text = _SECTION_HEADER_LINE_RE.sub("", article_body)
    text = _REVISION_NOTE_RE.sub("", text)
    return text


@dataclass
class Item:
    """호(1., 2., ...) 또는 목(가., 나., ...) 한 줄."""

    label: str
    body: str
    depth: int  # 0=호, 1=목


@dataclass
class Paragraph:
    """항(項) 하나. number=None이면 항 마커 없이 조문 본문이 바로 항인 경우."""

    number: int | None
    text: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Article:
    number: int
    sub_number: int | None  # "제17조의2"의 2
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)

    @property
    def label(self) -> str:
        base = f"제{self.number}조"
        return f"{base}의{self.sub_number}" if self.sub_number else base


def _split_items(body: str) -> tuple[str, list[Item]]:
    """항 본문에서 호/목 목록을 분리한다. (항 머리말, 호/목 리스트)를 반환."""
    matches = list(_ITEM_RE.finditer(body))
    if not matches:
        return body.strip(), []

    head = body[: matches[0].start()].strip()
    items: list[Item] = []
    for m in matches:
        depth = 1 if len(m.group("indent").expandtabs()) >= 4 else 0
        items.append(Item(label=m.group("label"), body=m.group("body").strip(), depth=depth))
    return head, items


def _split_paragraphs(article_body: str) -> list[Paragraph]:
    markers = list(_PARA_MARKER_RE.finditer(article_body))
    if not markers:
        head, items = _split_items(article_body)
        if not head and not items:
            return []
        return [Paragraph(number=None, text=head, items=items)]

    paragraphs: list[Paragraph] = []
    for i, m in enumerate(markers):
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(article_body)
        num = _CIRCLED_TO_INT[m.group(1)]
        head, items = _split_items(article_body[start:end])
        paragraphs.append(Paragraph(number=num, text=head, items=items))
    return paragraphs


def parse_articles(text: str) -> list[Article]:
    """법령 원문 md(frontmatter 제거 전이어도 무방) 전체에서 조문 목록을 뽑는다."""
    addenda_match = _ADDENDA_RE.search(text)
    if addenda_match:
        text = text[: addenda_match.start()]

    headers = list(_ARTICLE_HEADER_RE.finditer(text))
    articles: list[Article] = []
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = _strip_noise(text[start:end])
        articles.append(
            Article(
                number=int(m.group("num")),
                sub_number=int(m.group("sub")) if m.group("sub") else None,
                title=m.group("title"),
                paragraphs=_split_paragraphs(body),
            )
        )
    return articles
