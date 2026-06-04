#!/usr/bin/env node
/**
 * Elite plan panel → Cursor local agent (stdin JSON, stdout JSON).
 */
import { readFileSync } from "node:fs";
import { Agent } from "@cursor/sdk";

function out(obj, code = 0) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
  process.exit(code);
}

const raw = readFileSync(0, "utf8");
let input;
try {
  input = JSON.parse(raw);
} catch {
  out({ ok: false, error: "invalid stdin json" }, 1);
}

const apiKey = (input.apiKey || process.env.CURSOR_API_KEY || "").trim();
if (!apiKey) {
  out({ ok: false, error: "CURSOR_API_KEY missing" }, 1);
}

const cwd = input.cwd;
if (!cwd) {
  out({ ok: false, error: "cwd required" }, 1);
}

const model = input.model || "composer-2.5-fast";
const userMessage = input.userMessage || "";
if (!userMessage.trim()) {
  out({ ok: false, error: "userMessage empty" }, 1);
}

let agent;
try {
  if (input.agentId) {
    agent = Agent.resume(input.agentId, {
      apiKey,
      model: { id: model },
      local: { cwd, settingSources: [] },
    });
  } else {
    agent = Agent.create({
      apiKey,
      model: { id: model },
      local: { cwd, settingSources: [] },
    });
  }

  const run = await agent.send(userMessage);
  let text = "";
  for await (const event of run.stream()) {
    if (event.type === "assistant") {
      for (const block of event.message?.content || []) {
        if (block.type === "text") text += block.text;
      }
    }
  }
  const result = await run.wait();
  const agentId = agent.agentId ?? input.agentId ?? null;
  const status = result?.status ?? "unknown";
  if (status === "error") {
    out({
      ok: false,
      error: result?.result || "agent run error",
      agent_id: agentId,
      status,
    }, 2);
  }
  out({
    ok: true,
    text: text.trim(),
    agent_id: agentId,
    status,
  });
} catch (err) {
  const msg = err?.message || String(err);
  const retryable = Boolean(err?.isRetryable);
  out({ ok: false, error: msg, retryable }, 1);
} finally {
  if (agent) {
    try {
      await agent[Symbol.asyncDispose]();
    } catch {
      /* ignore */
    }
  }
}
