from szagent.graph.builder import build_graph


def main() -> None:
    graph = build_graph()
    result = graph.invoke({"messages": ["Hello, LangGraph!"]})
    print(result["messages"][-1])


if __name__ == "__main__":
    main()
