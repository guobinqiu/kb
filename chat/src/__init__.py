import os

# LangChain brings LangSmith transitively; never enable its environment tracking.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
