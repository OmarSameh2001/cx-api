# AI module

```
ai/
  route.py         mounts every AI feature under /ai
  errors.py        ai_unavailable (503) / ai_generation_failed (502), AI_ERROR_RESPONSES
  llm/             providers, fallback chain, generate_structured()
  prompts/         loader + shared/*.md (language, safety, fix)
  chatbot/form/    POST /ai/forms/generate, the reference feature
```

## Adding a feature

Example: `POST /ai/submissions/summary`.

1. **Folder.** `modules/ai/<group>/<feature>/` (e.g. `ai/chatbot/summary/`) with `__init__.py`.
2. **`schema.py`.** The pydantic model the LLM fills. Keep it easy for a model to fill: lists instead of free-keyed dicts, a `description=` on every non-obvious field (it is sent to the model).
3. **`prompts/`.** `system.md` (add `@include shared/language` and `@include shared/safety`), `user.md` with `$placeholders`, and `__init__.py` with `build_messages(request)` using `PromptDir(__file__)`.
4. **`mapper.py`.** `convert(draft) -> response`. Repair obvious slips quietly; for real problems raise `ValueError` (or let a pydantic DTO raise its `ValidationError`) and the message goes back to the model to fix.
5. **`dto.py`, `service.py`, `controller.py`, `route.py`**, like any module. The service is just:
   ```python
   FEATURE = "summary"  # env: AI_SUMMARY_PROVIDERS, AI_SUMMARY_MAX_TOKENS...

   async def summarize(request):
       return await generate_structured(
           FEATURE, GeneratedSummary, build_messages(request), lambda d: to_response(d, request)
       )
   ```
   The route is `async def` and passes `responses=AI_ERROR_RESPONSES`.
6. **Register** it in `modules/ai/route.py`: `router.include_router(summary_router)`.

That's all: provider fallback, cool-down, retries with error feedback, the deadline and the error format come from `generate_structured`.

## Settings (env)

| Variable | Default | Meaning |
|---|---|---|
| `AI_PROVIDERS` | `anthropic` | Provider order, first is primary. `name` or `name:model`. |
| `AI_<FEATURE>_PROVIDERS` | `AI_PROVIDERS` | Order for one feature only. |
| `AI_[<FEATURE>_]MAX_TOKENS` | 8000 | Reply size limit. |
| `AI_[<FEATURE>_]TIMEOUT_SECONDS` | 45 | One provider call. |
| `AI_[<FEATURE>_]TEMPERATURE` | provider's | Unset unless you need it. |
| `AI_[<FEATURE>_]MAX_ATTEMPTS` | 3 | Calls per request, including fixes. |
| `AI_[<FEATURE>_]DEADLINE_SECONDS` | 120 | No new attempt starts after this. |
| `AI_PROVIDER_COOLDOWN_SECONDS` | 60 | A failed provider is skipped this long. |
| `AI_PROVIDER_MAX_RETRIES` | 1 | SDK retries before falling over. |
| `<NAME>_API_KEY`, `_MODEL`, `_BASE_URL`, `_KIND`, `_KEY_ENVS`, `_NEEDS_KEY`, `_STRUCTURED_METHOD`, `_TEMPERATURE`, `_MAX_TOKENS`, `_TIMEOUT`, `_MAX_RETRIES` | `llm/providers.py` | Per provider; see `llm/config.py`. |

`<FEATURE>_X` wins over `AI_X`, which wins over the default. Settings are read at startup.

## Errors

Every AI route returns `{"error": code, "detail": message}`; `detail` is safe to show to users, specifics are in the log.

- `503 ai_unavailable`: no provider answered (outage, rate limit, bad key). Retry later.
- `502 ai_generation_failed`: providers answered, but no result passed validation. Rephrase.
- `422`: the request body is invalid (standard FastAPI shape).
