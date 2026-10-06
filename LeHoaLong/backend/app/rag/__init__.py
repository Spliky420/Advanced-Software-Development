"""RAG integration -- this backend as a client of the shared RAG server.

One module, because there is one job: ask the shared server a question and
return its grounded answer, its citations and its confidence category without
touching any of them.

The question-building for a goal lives in routes/rag.py rather than here,
because it is built entirely from figures this feature already computed -- it
is this service describing its own state, not RAG logic.
"""
