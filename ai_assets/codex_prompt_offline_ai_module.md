# Prompt for Codex — Integrate Human-Style Offline AI Module

You are modifying an existing application that already exists.
Your task is to integrate an **offline AI assistant module** into the app without requiring any cloud API.

## Objective
Build an AI module that:
1. Uses only local knowledge and local files.
2. Answers in Hebrew in a human, professional, and practical style.
3. Never fabricates facts when the local knowledge base does not contain enough information.
4. Returns structured results that the app can render.
5. Supports future expansion to local vector search / RAG.

## Knowledge Source
Use the local training dataset JSON file:
`offline_ai_training_dataset_1200.json`

The AI module should treat this file as the initial local knowledge base.

## Required behavior
The AI must:
- answer in natural Hebrew
- sound human and calm, not robotic
- begin with a short conclusion
- then explain briefly why
- then provide one practical next action
- explicitly state uncertainty when needed
- never invent a component, number, standard, or result that does not appear in the local knowledge base or app context
- prefer "אין לי מספיק מידע מקומי כדי לקבוע" over guessing

## Required output schema
Return an object with this shape:

```json
{
  "answer": "string",
  "confidence": "low | medium | high",
  "used_items": ["QA-0001", "QA-0042"],
  "missing_information": ["string"],
  "recommended_action": "string",
  "refusal": false
}
```

If there is not enough local evidence:
- set `refusal` to `true`
- explain what is missing
- keep the tone helpful and human

## Functional requirements
Implement:
1. Loader for the local JSON dataset
2. Retrieval layer:
   - start with simple lexical + keyword matching
   - prepare clean abstraction so it can later be replaced by embeddings/vector search
3. Prompt assembly layer:
   - inject only relevant retrieved items
   - do not dump the whole dataset into context
4. Response policy layer:
   - confidence scoring
   - refusal policy
   - human-style wording policy
5. Logging:
   - save timestamp, user question, used item ids, confidence, refusal flag
6. Settings/config:
   - path to local dataset
   - max retrieved items
   - minimum retrieval score for answering
   - toggle for strict refusal mode

## Non-functional requirements
- no external API calls
- deterministic and maintainable code
- clear module boundaries
- easy to test
- no hidden prompts spread across many files; keep prompt assets centralized
- support Hebrew UTF-8 correctly

## Human answer style rules
- Write as a knowledgeable colleague.
- Be concise but not abrupt.
- Avoid heavy jargon unless the question clearly demands it.
- If the question is simple, answer simply.
- If the question is technical, still keep the opening sentence easy to understand.
- Do not overpromise.
- Do not act as if internet access exists.
- Do not mention model limitations unless relevant to the answer.

## Suggested module structure
- `ai/knowledge_loader.*`
- `ai/retriever.*`
- `ai/policy.*`
- `ai/formatter.*`
- `ai/service.*`

## Retrieval policy
For each user question:
1. normalize text
2. retrieve top relevant items from the local dataset
3. if no strong matches exist:
   - return a helpful refusal
4. if matches exist:
   - synthesize an answer from them
   - cite the used item ids internally in the result object

## Important
Do not "train" a remote model.
Do not add dependencies on OpenAI, Claude, or any other paid API.
The solution must work fully offline inside the existing app.

## Deliverables
1. integrated AI module
2. configuration file
3. tests for:
   - successful answer
   - insufficient information
   - contradictory local knowledge
   - human-style output
4. short README for how the module works
