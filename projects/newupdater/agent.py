from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from src.newupdater.tools import search_news

load_dotenv()

tools = [search_news]

model = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
)

model_with_tools = model.bind_tools(tools)

def call_model(state: MessagesState):
    """Ask the model what to do next."""
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


graph_builder = StateGraph(MessagesState)

graph_builder.add_node("model", call_model)
graph_builder.add_node("tools", ToolNode(tools))

graph_builder.add_edge(START, "model")

graph_builder.add_conditional_edges(
    "model",
    tools_condition,
    {
        "tools": "tools",
        END: END,
    },
)

graph_builder.add_edge("tools", "model")

agent = graph_builder.compile()


def run_agent(question: str):
    """Run one agent task and return its final answer."""
    result = agent.invoke(
        {
            "messages": [
                SystemMessage(
                    content=(
                        "You are NewUpdater, a technology research assistant. "
                        "Use the search_news tool when you need information "
                        "from the NewUpdater index. Clearly distinguish "
                        "demo data from verified current news. "
                        "Do not invent sources or dates."
                    )
                ),
                HumanMessage(content=question),
            ]
        },
        config={"recursion_limit": 10},
    )

    return result["messages"][-1].content


if __name__ == "__main__":
    question = input("Ask NewUpdater: ").strip()

    if not question:
        raise SystemExit("Please enter a question.")

    try:
        answer = run_agent(question)
        print("\nNewUpdater:\n")
        print(answer)
    except Exception as exc:
        print(f"\nAgent failed: {type(exc).__name__}: {exc}")