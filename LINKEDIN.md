# LinkedIn launch draft

I wanted to understand what is actually inside an AI agent, so I built a small one from first principles.

**Loop Ledger** has four parts:

→ a readable reason–act–observe loop
→ a registry of safe local tools
→ durable SQLite memory
→ a live trace that shows every step of a turn

The demo runs without an API key, and the whole backend is plain Python. You can ask it to calculate something, save the result, restart it, and recall the memory later.

This was inspired by transparent agent projects such as Waku, but implemented from scratch as a smaller learning build. My goal was not to create another chatbot. It was to make the system behind one visible and understandable.

Code: **https://github.com/LobsterQBA/loop-ledger**

What is the smallest agent architecture you would still call useful?

#AIEngineering #AIAgents #Python #BuildInPublic #LLMOps
