from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
import os
from dotenv import load_dotenv
load_dotenv()
from langgraph.graph import START, StateGraph, MessagesState
from langgraph.checkpoint.memory import MemorySaver
import secrets
import asyncio
from query import Query


class LLM:

    running = []

    def __init__(self):

        self.dev = False
        # LLM Workflow Definition - Try Ollama first (primary), fallback to Groq
        self.mdl = None
        
        # Try Ollama first (primary)
        try:
            ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
            ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
            print(f"Attempting to initialize Ollama model: {ollama_model}")
            self.mdl = ChatOllama(
                model=ollama_model,
                base_url=ollama_url,
                temperature=0,
                streaming=True
            )
            print(f"[SUCCESS] Successfully initialized Ollama model: {ollama_model}")
        except Exception as e:
            print(f"[ERROR] Failed to initialize Ollama: {e}")
            # Fallback to Groq models
            try:
                print("Attempting to initialize Groq model: groq/compound-mini (fallback)")
                self.mdl = ChatGroq(
                    model='groq/compound-mini',
                    api_key=os.getenv('GROQ_API_KEY'),
                    temperature=0.3,
                    streaming=True
                )
                print("[SUCCESS] Successfully initialized Groq model: groq/compound-mini")
            except Exception as e2:
                print(f"[ERROR] Failed to initialize groq/compound-mini: {e2}")
                # Try groq/compound as final fallback
                try:
                    print("Attempting to initialize Groq model: groq/compound (fallback)")
                    self.mdl = ChatGroq(
                        model='groq/compound',
                        api_key=os.getenv('GROQ_API_KEY'),
                        temperature=0.3,
                        streaming=True
                    )
                    print("[SUCCESS] Successfully initialized Groq model: groq/compound")
                except Exception as e3:
                    print(f"[ERROR] Failed to initialize all models. Last error: {e3}")
                    raise Exception(f"Could not initialize any LLM model. Ollama error: {e}. Groq errors: {e2}, {e3}")
        
        if self.mdl is None:
            raise Exception("LLM model initialization failed - no model was successfully initialized")

        self._id = secrets.token_hex(4)
        LLM.running.append(self._id)

        # Define a new graph
        workflow = StateGraph(state_schema=MessagesState)
        # print("Workflow:", workflow)
        # Define the (single) node in the graph
        workflow.add_edge(START, "model")
        workflow.add_node("model", self.__call_model)
        # Add memory
        memory = MemorySaver()
        self.app = workflow.compile(checkpointer=memory)
        # print("Workflow compiled with memory:", memory)
        # print("Agent ready to run.")

        # Asynchronous Queues
        self.inpq = asyncio.Queue()
        self.outq = asyncio.Queue()

    def __call_model(self, state: MessagesState):
        resp = self.mdl.invoke(state["messages"])
        return {"messages": resp}

    async def run(self):

        self.dev = False
        pipeline_task = asyncio.create_task(
            self.pipeline(self.inpq, self.outq)
        )
        # print_task = asyncio.create_task(
        #     self.print_queue(self.outq)
        # )

        await asyncio.gather(
            pipeline_task,
            # print_task
        )

    async def pipeline(self, inpq: asyncio.Queue, outq: asyncio.Queue):
        try:
            while True:
                prompt = await inpq.get()

                print("\n--- Pipeline received input ---")
                print("\nUser :", prompt.raw()[-1].content)

                async for resp in self.app.astream(
                    {"messages": prompt.raw()},
                    {"configurable": {"thread_id": self._id}}
                ):
                    reply = resp['model']['messages'].content
                    await outq.put(reply)

                print(f"\n{self._id} : {reply}")
                print("\n--- End of response ---")
                await outq.put("<EOL>")
                # if all([(x in prompt.raw()[-1].content) for x in ['thank', 'you']]):
                #     break

            # await outq.put(None)

        except Exception as e:
            print(f"Pipeline error: {e}")

    async def print_queue(self, queue: asyncio.Queue):
        while True:
            item = await queue.get()
            if isinstance(item, str):
                print(f"\n{self._id} : {item}")


async def start():
    llm = LLM()
    asyncio.create_task(llm.run())
    await asyncio.sleep(2)  # Give pipeline time to start

    msg = "Hi, My full name is Demo, Py"
    await llm.inpq.put( Query(msg) )
    await asyncio.sleep(2)
    msg = "Hi, What is my full name ?"
    await llm.inpq.put( Query(msg) )
    await asyncio.sleep(2)
    msg = "What is the Capital of France ?"
    await llm.inpq.put( Query(msg) )
    await asyncio.sleep(2)
    msg = "Let us check if you remember my name now ?"
    await llm.inpq.put( Query(msg) )
    await asyncio.sleep(2)
    msg = "then, spell my name"
    await llm.inpq.put( Query(msg) )
    await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(start())
