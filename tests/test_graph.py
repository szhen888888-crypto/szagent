from szagent.graph.builder import build_graph


def test_graph_responds() -> None:
    graph = build_graph()

    result = graph.invoke({"messages": ["ping"]})

    assert result["messages"][-1] == "Received: ping"
