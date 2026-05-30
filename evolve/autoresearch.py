"""Autoresearch sub-agent.

Each generation (or every N gens), this agent:
  1. Pulls fresh arxiv listings filtered by keywords (Lean, formal proof, RLVR,
     theorem proving, magma, equational).
  2. Diffs against the last seen set in `seen.json`.
  3. For new entries, fetches abstract; if it scores high on technique-extraction
     heuristics, proposes a new Arm to add to the hypothesis library.
  4. Emits proposals to `proposals.jsonl` for human review (or auto-merge if a
     confidence threshold is set).

Heuristic: count tokens from technique vocabulary in the abstract:
  reward shaping, curriculum, subgoal, distill, cheatsheet, verifier, tactic,
  counterexample, magma, GRPO, RLOO, DPO, MoE, LoRA, quantization, prompt.

Above threshold -> emit proposal. Below -> skip but log.

Storage:
  evolve/autoresearch/seen.json     -- arxiv IDs already considered
  evolve/autoresearch/proposals.jsonl  -- one JSON per new arm proposal
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_log = logging.getLogger(__name__)


VOCAB = {
    "reward": 2,
    "shaping": 2,
    "curriculum": 2,
    "subgoal": 3,
    "decomposition": 2,
    "distill": 2,
    "cheat-sheet": 3,
    "cheatsheet": 3,
    "verifier": 2,
    "tactic": 3,
    "counterexample": 3,
    "magma": 4,
    "equational": 4,
    "GRPO": 3,
    "RLOO": 3,
    "PPO": 1,
    "DPO": 1,
    "MoE": 1,
    "LoRA": 2,
    "quantization": 1,
    "prompt": 1,
    "Lean": 3,
    "miniF2F": 3,
    "proof": 2,
    "rollout": 1,
}
QUERIES = [
    "Lean 4 theorem proving",
    "formal proof reinforcement learning",
    "RLVR verifiable reward",
    "magma equational theory",
    "GRPO reasoning LLM",
    "neural theorem prover",
]
_ARXIV_QUERY_TPL = "/api/query?search_query={q}&start=0&max_results=10&sortBy=submittedDate&sortOrder=descending"
ARXIV_API = os.environ.get(
    "LAWFORGE_ARXIV_API", "http" + "://export.arxiv.org" + _ARXIV_QUERY_TPL
)


@dataclass
class Paper:
    id: str
    title: str
    abstract: str
    url: str


def fetch_arxiv(query: str) -> list[Paper]:
    url = ARXIV_API.format(q=quote_plus(query))
    req = Request(url, headers={"User-Agent": "eqt-trm-autoresearch/0.1"})
    with urlopen(req, timeout=20) as r:
        xml = r.read().decode()
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, flags=re.S):
        aid = re.search(r"<id>(.*?)</id>", entry).group(1).strip()
        title = re.search(r"<title>(.*?)</title>", entry, flags=re.S).group(1).strip()
        abstract = (
            re.search(r"<summary>(.*?)</summary>", entry, flags=re.S).group(1).strip()
        )
        out.append(Paper(id=aid, title=title, abstract=abstract, url=aid))
    return out


def score(text: str) -> int:
    text_l = text.lower()
    s = 0
    for k, v in VOCAB.items():
        s += text_l.count(k.lower()) * v
    return s


def propose_arm(paper: Paper, score_v: int) -> dict:
    return {
        "id": paper.id.rsplit("/", 1)[-1],
        "title": paper.title,
        "url": paper.url,
        "score": score_v,
        "abstract_excerpt": paper.abstract[:600],
        "suggested_arm_name": f"arxiv_{paper.id.rsplit('/', 1)[-1]}",
        "rationale": "abstract matched technique vocab over threshold",
        "draft_hypothesis": (
            "Adapt the technique described in the abstract: read paper, extract "
            "the core trick (reward / curriculum / tactic / decomposition), "
            "implement minimal version in train.py."
        ),
    }


def run(out_dir: Path, threshold: int = 10):
    import concurrent.futures as cf

    out_dir.mkdir(parents=True, exist_ok=True)
    seen_path = out_dir / "seen.json"
    proposals_path = out_dir / "proposals.jsonl"
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    new_count = 0
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        # arxiv ToS: <= 3 req/s; 3 concurrent workers is the cap.
        results = list(ex.map(_safe_fetch, QUERIES))
    for q, papers in zip(QUERIES, results):
        if papers is None:
            continue
        for p in papers:
            if p.id in seen:
                continue
            seen.add(p.id)
            s = score(p.title + " " + p.abstract)
            if s >= threshold:
                prop = propose_arm(p, s)
                with proposals_path.open("a") as f:
                    f.write(json.dumps(prop) + "\n")
                new_count += 1
                print(f"[autoresearch] proposal: {p.title[:80]} (score={s})")
    seen_path.write_text(json.dumps(sorted(seen)))
    print(f"[autoresearch] new proposals: {new_count}")


def _safe_fetch(q: str) -> list[Paper] | None:
    try:
        return fetch_arxiv(q)
    except Exception as e:
        _log.warning("query failed %r: %s", q, e)
        return None


if __name__ == "__main__":
    run(Path(__file__).parent / "autoresearch")
