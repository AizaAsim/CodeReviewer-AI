"""LangGraph wiring for the classified fan-out review flow."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from codereviewer.agent.nodes.aggregate_findings import aggregate_findings
from codereviewer.agent.nodes.classify_files import classify_files
from codereviewer.agent.nodes.decide import decide
from codereviewer.agent.nodes.fetch_pr_context import fetch_pr_context
from codereviewer.agent.nodes.filter_noise import filter_noise_node
from codereviewer.agent.nodes.logic_pass import logic_pass
from codereviewer.agent.nodes.post_review import post_review
from codereviewer.agent.nodes.security_pass import security_pass
from codereviewer.agent.nodes.severity_gate import severity_gate
from codereviewer.agent.nodes.skip_node import skip_node
from codereviewer.agent.nodes.style_pass import style_pass
from codereviewer.agent.state import ReviewState


def route_review_passes(state: ReviewState):
    if not state["files"]:
        return "skip_node"

    sends: list[Send] = []
    allow_style = state["budget"].remaining / max(1, state["budget"].total) > 0.3

    for file in state["files"]:
        file_class = state["classifications"].get(file.path)
        if file_class is None:
            continue

        branch_state = {
            "run_id": state["run_id"],
            "repo": state["repo"],
            "pr_number": state["pr_number"],
            "installation_id": state.get("installation_id"),
            "pr": state["pr"],
            "raw_files": [],
            "files": state["files"],
            "current_file": file,
            "classifications": state["classifications"],
            "findings": [],
            "filtered": [],
            "decision": state["decision"],
            "posted": [],
            "budget": state["budget"],
            "token_events": [],
        }
        # Secrets often live in config modules — always security-scan those,
        # plus any high-risk or application-logic file.
        if (
            file_class.risk == "high"
            or file_class.kind in ("logic", "config")
        ):
            sends.append(Send("security_pass", branch_state))
        # Skip logic pass on low-risk helpers/formatters — they draw invented
        # correctness findings and drown out real style nits.
        if file_class.kind == "logic" and file_class.risk != "low":
            sends.append(Send("logic_pass", branch_state))
        if allow_style and file_class.kind != "docs":
            sends.append(Send("style_pass", branch_state))

    return sends or "aggregate_findings"


def build_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("fetch_pr_context", fetch_pr_context)
    graph.add_node("filter_noise", filter_noise_node)
    graph.add_node("classify_files", classify_files)
    graph.add_node("security_pass", security_pass)
    graph.add_node("logic_pass", logic_pass)
    graph.add_node("style_pass", style_pass)
    graph.add_node("aggregate_findings", aggregate_findings)
    graph.add_node("severity_gate", severity_gate)
    graph.add_node("decide", decide)
    graph.add_node("post_review", post_review)
    graph.add_node("skip_node", skip_node)

    graph.add_edge(START, "fetch_pr_context")
    graph.add_edge("fetch_pr_context", "filter_noise")
    graph.add_edge("filter_noise", "classify_files")
    graph.add_conditional_edges("classify_files", route_review_passes)
    graph.add_edge("security_pass", "aggregate_findings")
    graph.add_edge("logic_pass", "aggregate_findings")
    graph.add_edge("style_pass", "aggregate_findings")
    graph.add_edge("aggregate_findings", "severity_gate")
    graph.add_edge("severity_gate", "decide")
    graph.add_edge("decide", "post_review")
    graph.add_edge("post_review", END)
    graph.add_edge("skip_node", END)
    return graph.compile()


def build_eval_graph():
    """Same review pipeline as production, but stops before posting to GitHub."""
    graph = StateGraph(ReviewState)
    graph.add_node("fetch_pr_context", fetch_pr_context)
    graph.add_node("filter_noise", filter_noise_node)
    graph.add_node("classify_files", classify_files)
    graph.add_node("security_pass", security_pass)
    graph.add_node("logic_pass", logic_pass)
    graph.add_node("style_pass", style_pass)
    graph.add_node("aggregate_findings", aggregate_findings)
    graph.add_node("severity_gate", severity_gate)
    graph.add_node("decide", decide)
    graph.add_node("skip_node", skip_node)

    graph.add_edge(START, "fetch_pr_context")
    graph.add_edge("fetch_pr_context", "filter_noise")
    graph.add_edge("filter_noise", "classify_files")
    graph.add_conditional_edges("classify_files", route_review_passes)
    graph.add_edge("security_pass", "aggregate_findings")
    graph.add_edge("logic_pass", "aggregate_findings")
    graph.add_edge("style_pass", "aggregate_findings")
    graph.add_edge("aggregate_findings", "severity_gate")
    graph.add_edge("severity_gate", "decide")
    graph.add_edge("decide", END)
    graph.add_edge("skip_node", END)
    return graph.compile()


review_graph = build_graph()
