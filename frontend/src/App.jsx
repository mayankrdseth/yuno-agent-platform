import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  addEdge,
  useEdgesState,
  useNodesState,
} from "reactflow";
import "reactflow/dist/style.css";

const API_BASE = "http://127.0.0.1:8000";

const AVAILABLE_TOOLS = ["web_search", "wikipedia", "calculator", "datetime"];
const AVAILABLE_CHANNELS = ["telegram", "slack", "whatsapp"];
const AVAILABLE_MODELS = [
  "llama-3.3-70b-versatile",
  "llama-3.1-8b-instant",
  "mixtral-8x7b-32768",
  "gemma2-9b-it",
  "llama-3.1-70b-specdec",
];

/* ─────────────────────────────────────────────
   Helpers
───────────────────────────────────────────── */
function parseList(val) {
  if (Array.isArray(val)) return val;
  try { return JSON.parse(val || "[]"); } catch { return []; }
}

function buildAgentNode(agent, position) {
  return {
    id: String(agent.id),
    type: "agentNode",
    position,
    data: {
      name: agent.name,
      role: agent.role,
      tools: parseList(agent.tools),
      channels: parseList(agent.channels),
      pending: false,
    },
  };
}

function buildHubLayout(agents) {
  if (!agents.length) return { nodes: [], edges: [] };
  const orch = agents.find((a) => a.role === "orchestrator");
  if (!orch) {
    const nodes = agents.map((a, i) => buildAgentNode(a, { x: 80 + i * 280, y: 160 }));
    const edges = agents.slice(0, -1).map((a, i) => ({
      id: `e${a.id}-${agents[i + 1].id}`,
      source: String(a.id),
      target: String(agents[i + 1].id),
      animated: true,
      style: { stroke: "#1affd5", strokeWidth: 2 },
    }));
    return { nodes, edges };
  }
  const specialists = agents.filter((a) => a.id !== orch.id);
  const totalSpec = specialists.length;
  const centerY = totalSpec <= 1 ? 160 : 60 + ((totalSpec - 1) * 160) / 2;
  const nodes = [
    buildAgentNode(orch, { x: 80, y: centerY }),
    ...specialists.map((a, i) => buildAgentNode(a, { x: 420, y: 60 + i * 160 })),
  ];
  const edges = specialists.map((a) => ({
    id: `e${orch.id}-${a.id}`,
    source: String(orch.id),
    target: String(a.id),
    animated: true,
    style: { stroke: "#f59e0b80", strokeWidth: 1.5, strokeDasharray: "5 3" },
  }));
  return { nodes, edges };
}

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDuration(startIso, endIso) {
  if (!startIso || !endIso) return null;
  const ms = new Date(endIso) - new Date(startIso);
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtCost(tokens) {
  if (!tokens) return null;
  const cost = (tokens / 1000) * 0.0002;
  return `~$${cost.toFixed(5)}`;
}

/* ─────────────────────────────────────────────
   Custom ReactFlow Node
───────────────────────────────────────────── */
function CustomAgentNode({ data }) {
  const tools = data.tools || [];
  const channels = data.channels || [];
  const isOrchestrator = data.role === "orchestrator";

  let displayTools;
  let extraTools = 0;
  if (isOrchestrator) {
    const pinned = ["calculator", "datetime"].filter((t) => tools.includes(t));
    const rest = tools.filter((t) => !pinned.includes(t));
    displayTools = [...pinned, ...rest];
  } else {
    displayTools = tools.slice(0, 3);
    extraTools = tools.length - displayTools.length;
  }

  return (
    <div style={{
      background: "#1a1f2e",
      border: isOrchestrator
        ? "1.5px solid #f59e0b"
        : data.pending ? "2px dashed #1affd5" : "1px solid #2d3348",
      borderRadius: 10,
      padding: "10px 14px",
      minWidth: 180,
      maxWidth: 240,
      boxShadow: isOrchestrator ? "0 0 10px rgba(245,158,11,0.15)" : "0 4px 16px rgba(0,0,0,0.4)",
      cursor: "grab",
    }}>
      <Handle type="target" position={Position.Left}
        style={{ background: isOrchestrator ? "#f59e0b" : "#1affd5", width: 10, height: 10, border: "2px solid #0f1117" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 2 }}>
        {isOrchestrator && (
          <span style={{ fontSize: 9, background: "#f59e0b18", color: "#f59e0b", border: "1px solid #f59e0b35", borderRadius: 3, padding: "1px 5px", fontWeight: 700, letterSpacing: "0.04em" }}>ORCHESTRATOR</span>
        )}
      </div>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#e8e8e8", marginBottom: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data.name}</div>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>{data.role}</div>
      {displayTools.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3, marginBottom: 4 }}>
          {displayTools.map((t) => {
            const isPinned = isOrchestrator && (t === "calculator" || t === "datetime");
            return (
              <span key={t} style={{
                background: isPinned ? "#1affd522" : "#f59e0b22",
                color: isPinned ? "#1affd5" : "#f59e0b",
                border: `1px solid ${isPinned ? "#1affd544" : "#f59e0b44"}`,
                borderRadius: 4, fontSize: 10, padding: "1px 5px", fontWeight: 600,
              }}>{isPinned ? "⚡" : "🔧"} {t}</span>
            );
          })}
          {extraTools > 0 && <span style={{ fontSize: 10, color: "#6b7280" }}>+{extraTools} more</span>}
        </div>
      )}
      {channels.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
          {channels.map((c) => (
            <span key={c} style={{ background: "#0ea5e922", color: "#0ea5e9", border: "1px solid #0ea5e944", borderRadius: 4, fontSize: 10, padding: "1px 5px", fontWeight: 600 }}>📡 {c}</span>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Right}
        style={{ background: isOrchestrator ? "#f59e0b" : "#1affd5", width: 10, height: 10, border: "2px solid #0f1117" }} />
    </div>
  );
}

const nodeTypes = { agentNode: CustomAgentNode };

/* ─────────────────────────────────────────────
   Collapsible Sidebar Section
───────────────────────────────────────────── */
function SidebarSection({ title, badge, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ borderBottom: "1px solid #1e2538" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "10px 0", background: "transparent", border: "none",
          color: "#e8e8e8", cursor: "pointer", fontSize: 13, fontWeight: 700,
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {title}
          {badge != null && (
            <span style={{ fontSize: 10, background: "#1affd520", color: "#1affd5", border: "1px solid #1affd530", borderRadius: 99, padding: "1px 7px", fontWeight: 700 }}>{badge}</span>
          )}
        </span>
        <span style={{ fontSize: 11, color: "#6b7280", transform: open ? "rotate(180deg)" : "none", transition: "transform 0.18s" }}>▼</span>
      </button>
      {open && <div style={{ paddingBottom: 14 }}>{children}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────
   Edit Agent Modal
───────────────────────────────────────────── */
function EditAgentModal({ agent, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: agent.name,
    role: agent.role,
    system_prompt: agent.system_prompt || "",
    model: agent.model || "llama-3.3-70b-versatile",
    tools: parseList(agent.tools),
    channels: parseList(agent.channels),
    max_iterations: agent.max_iterations ?? 5,
    memory_enabled: agent.memory_enabled ?? true,
    is_active: agent.is_active ?? true,
    forbidden_topics: Array.isArray(agent.forbidden_topics)
      ? agent.forbidden_topics.join(", ")
      : (agent.forbidden_topics || ""),
    max_output_chars: agent.max_output_chars ?? "",
    skills: Array.isArray(agent.skills)
      ? agent.skills.join(", ")
      : (agent.skills || ""),
    interaction_rules: Array.isArray(agent.interaction_rules)
      ? agent.interaction_rules.join("\n")
      : (agent.interaction_rules || ""),
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const isOrch = form.role === "orchestrator";

  function toggleTool(tool) {
    setForm((f) => ({ ...f, tools: f.tools.includes(tool) ? f.tools.filter((t) => t !== tool) : [...f.tools, tool] }));
  }
  function toggleChannel(ch) {
    setForm((f) => ({ ...f, channels: f.channels.includes(ch) ? f.channels.filter((c) => c !== ch) : [...f.channels, ch] }));
  }

  async function handleSave() {
    setSaving(true); setError("");
    try {
      let tools = form.tools;
      if (isOrch) tools = [...new Set(["calculator", "datetime", ...tools])];
      const payload = {
        ...form, tools,
        forbidden_topics: form.forbidden_topics ? form.forbidden_topics.split(",").map((s) => s.trim()).filter(Boolean) : [],
        max_output_chars: form.max_output_chars ? parseInt(form.max_output_chars, 10) : null,
        channels: isOrch ? form.channels : [],
        skills: form.skills ? form.skills.split(",").map((s) => s.trim()).filter(Boolean) : [],
        interaction_rules: form.interaction_rules ? form.interaction_rules.split("\n").map((s) => s.trim()).filter(Boolean) : [],
      };
      await axios.patch(`${API_BASE}/agents/${agent.id}`, payload);
      onSaved(); onClose();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save changes.");
    } finally { setSaving(false); }
  }

  return (
    <div onClick={(e) => e.target === e.currentTarget && onClose()} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, backdropFilter: "blur(4px)" }}>
      <div style={{ background: "#1a1f2e", border: "1px solid #2d3348", borderRadius: 12, padding: 24, width: "min(560px, 95vw)", maxHeight: "90vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.6)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 10, color: "#1affd5", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>Edit Agent</div>
            <div style={{ fontWeight: 700, fontSize: 16, color: "#e8e8e8" }}>{agent.name}</div>
          </div>
          <button onClick={onClose} style={{ background: "transparent", border: "none", color: "#6b7280", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div className="form-grid">
          <div><div className="muted-small" style={{ marginBottom: 4 }}>Name</div><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div>
            <div className="muted-small" style={{ marginBottom: 4 }}>Role</div>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value, channels: [] })} style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
              <option value="agent">Agent</option>
              <option value="orchestrator">Orchestrator</option>
            </select>
          </div>
          <div><div className="muted-small" style={{ marginBottom: 4 }}>System Prompt</div><textarea rows={5} value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} style={{ resize: "vertical" }} /></div>
          <div>
            <div className="muted-small" style={{ marginBottom: 4 }}>Model</div>
            <select value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
              {AVAILABLE_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <div className="muted-small" style={{ marginBottom: 6 }}>Tools {isOrch && <span style={{ marginLeft: 8, fontSize: 10, color: "#1affd5" }}>⚡ calculator &amp; datetime always active</span>}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {AVAILABLE_TOOLS.map((tool) => {
                const isPinned = isOrch && (tool === "calculator" || tool === "datetime");
                return (
                  <label key={tool} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: isPinned ? "default" : "pointer", opacity: isPinned ? 0.7 : 1 }}>
                    <input type="checkbox" checked={isPinned ? true : form.tools.includes(tool)} disabled={isPinned} onChange={() => !isPinned && toggleTool(tool)} />
                    {tool}{isPinned ? " 🔒" : ""}
                  </label>
                );
              })}
            </div>
          </div>
          {isOrch && (
            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Channels <span style={{ color: "#f59e0b", fontSize: 10 }}>(orchestrator only)</span></div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {AVAILABLE_CHANNELS.map((ch) => (
                  <label key={ch} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={form.channels.includes(ch)} onChange={() => toggleChannel(ch)} />
                    {ch}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div><div className="muted-small" style={{ marginBottom: 4 }}>Forbidden Topics <span style={{ color: "#6b7280", fontSize: 10 }}>(comma-separated)</span></div><input value={form.forbidden_topics} onChange={(e) => setForm({ ...form, forbidden_topics: e.target.value })} placeholder="e.g. violence, politics" /></div>
          <div><div className="muted-small" style={{ marginBottom: 4 }}>Skills <span style={{ color: "#6b7280", fontSize: 10 }}>(comma-separated)</span></div><input value={form.skills} onChange={(e) => setForm({ ...form, skills: e.target.value })} placeholder="e.g. summarisation, code_review" /></div>
          <div><div className="muted-small" style={{ marginBottom: 4 }}>Interaction Rules <span style={{ color: "#6b7280", fontSize: 10 }}>(one per line)</span></div><textarea rows={3} value={form.interaction_rules} onChange={(e) => setForm({ ...form, interaction_rules: e.target.value })} placeholder="e.g. always reply in bullet points" style={{ resize: "vertical" }} /></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div><div className="muted-small" style={{ marginBottom: 4 }}>Max Iterations</div><input type="number" min={1} max={20} value={form.max_iterations} onChange={(e) => setForm({ ...form, max_iterations: Number(e.target.value) })} /></div>
            <div><div className="muted-small" style={{ marginBottom: 4 }}>Max Output Chars</div><input type="number" value={form.max_output_chars} onChange={(e) => setForm({ ...form, max_output_chars: e.target.value })} placeholder="optional" /></div>
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />Active</label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}><input type="checkbox" checked={form.memory_enabled} onChange={(e) => setForm({ ...form, memory_enabled: e.target.checked })} />Memory enabled</label>
          </div>
        </div>
        {error && <div style={{ color: "#f87171", fontSize: 12, marginTop: 12, padding: "6px 10px", background: "#f8717115", borderRadius: 6, border: "1px solid #f8717130" }}>⚠ {error}</div>}
        <div style={{ display: "flex", gap: 8, marginTop: 20, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #2d3348", background: "transparent", color: "#6b7280", cursor: "pointer", fontSize: 13 }}>Cancel</button>
          <button onClick={handleSave} disabled={saving} className="primary-btn" style={{ padding: "8px 20px", fontSize: 13 }}>{saving ? "Saving..." : "Save changes"}</button>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   Run Detail Panel — tabbed
───────────────────────────────────────────── */
function RunDetailPanel({ run, messages, onClose }) {
  const [tab, setTab] = useState("timeline");

  const timeline = useMemo(() => {
    return [...messages].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
  }, [messages]);

  const agentMessages = useMemo(() => timeline.filter((m) => ["input", "output", "agent_message"].includes(m.message_type)), [timeline]);
  const toolCalls = useMemo(() => timeline.filter((m) => m.message_type === "tool_call"), [timeline]);

  const duration = fmtDuration(run.created_at, run.completed_at);
  const cost = fmtCost(run.total_tokens);

  const TABS = [
    { id: "timeline", label: `Timeline (${timeline.length})` },
    { id: "messages", label: `Messages (${agentMessages.length})` },
    { id: "tools",    label: `Tool Calls (${toolCalls.length})` },
    { id: "stats",   label: "Stats" },
  ];

  const typeColor = { input: "#0ea5e9", output: "#22c55e", log: "#6b7280", agent_message: "#8b5cf6", tool_call: "#f59e0b", error: "#ef4444" };

  const typeIcon = { input: "→", output: "←", log: "·", agent_message: "💬", tool_call: "🔧", error: "✕" };

  function Tag({ type }) {
    return (
      <span style={{ display: "inline-block", fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 4, background: (typeColor[type] || "#6b7280") + "22", color: typeColor[type] || "#6b7280", border: `1px solid ${(typeColor[type] || "#6b7280")}44` }}>
        {type}
      </span>
    );
  }

  function renderContent(content) {
    if (!content) return <span style={{ color: "#6b7280", fontStyle: "italic" }}>—</span>;
    let str = typeof content === "string" ? content : JSON.stringify(content, null, 2);
    return (
      <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "inherit", fontSize: 12, color: "#d1d5db", lineHeight: 1.55 }}>{str}</pre>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 16px", borderBottom: "1px solid #2d3348", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: run.status === "completed" ? "#22c55e22" : run.status === "failed" ? "#ef444422" : "#f59e0b22", color: run.status === "completed" ? "#22c55e" : run.status === "failed" ? "#ef4444" : "#f59e0b", border: `1px solid ${run.status === "completed" ? "#22c55e44" : run.status === "failed" ? "#ef444444" : "#f59e0b44"}` }}>
            {run.status?.toUpperCase()}
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#e8e8e8" }}>Run #{run.id}</span>
          <span style={{ fontSize: 11, color: "#6b7280" }}>{run.created_at ? new Date(run.created_at).toLocaleString() : ""}</span>
        </div>
        <button onClick={onClose} style={{ background: "transparent", border: "none", color: "#6b7280", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: "2px 6px" }}>✕</button>
      </div>

      {/* Input preview */}
      <div style={{ padding: "8px 16px", borderBottom: "1px solid #2d3348", flexShrink: 0, background: "#0f111788" }}>
        <span style={{ fontSize: 10, color: "#6b7280", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>Input: </span>
        <span style={{ fontSize: 12, color: "#9ca3af" }}>{run.input_text || "—"}</span>
      </div>

      {/* Sub-tabs */}
      <div style={{ display: "flex", gap: 2, padding: "8px 16px 0", borderBottom: "1px solid #2d3348", flexShrink: 0 }}>
        {TABS.map(({ id, label }) => (
          <button key={id} onClick={() => setTab(id)} style={{ fontSize: 11, fontWeight: tab === id ? 700 : 500, padding: "5px 12px", borderRadius: "5px 5px 0 0", border: tab === id ? "1px solid #2d3348" : "1px solid transparent", borderBottom: tab === id ? "1px solid #0f1117" : "1px solid transparent", background: tab === id ? "#0f1117" : "transparent", color: tab === id ? "#e8e8e8" : "#6b7280", cursor: "pointer", marginBottom: -1, transition: "color 0.15s" }}>
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>

        {/* TIMELINE */}
        {tab === "timeline" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {timeline.length === 0 && <div style={{ color: "#6b7280", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No events recorded.</div>}
            {timeline.map((m, i) => (
              <div key={m.id || i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                {/* Timeline spine */}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0, width: 20 }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: typeColor[m.message_type] || "#6b7280", marginTop: 4, flexShrink: 0 }} />
                  {i < timeline.length - 1 && <div style={{ width: 1, flex: 1, minHeight: 12, background: "#2d3348", margin: "2px 0" }} />}
                </div>
                <div style={{ flex: 1, minWidth: 0, padding: "4px 10px 8px", background: "#0f1117", borderRadius: 6, border: "1px solid #2d3348" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                    <Tag type={m.message_type} />
                    {m.agent_name && <span style={{ fontSize: 11, color: "#f59e0b", fontWeight: 600 }}>{m.agent_name}</span>}
                    {m.created_at && <span style={{ fontSize: 10, color: "#6b7280", marginLeft: "auto" }}>{fmtTime(m.created_at)}</span>}
                  </div>
                  {renderContent(m.content)}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* MESSAGES */}
        {tab === "messages" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {agentMessages.length === 0 && <div style={{ color: "#6b7280", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No agent messages.</div>}
            {agentMessages.map((m, i) => (
              <div key={m.id || i} style={{ padding: "10px 12px", background: "#0f1117", borderRadius: 8, border: "1px solid #2d3348" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                  <Tag type={m.message_type} />
                  {m.agent_name && <span style={{ fontSize: 11, color: "#f59e0b", fontWeight: 600 }}>{m.agent_name}</span>}
                  {m.created_at && <span style={{ fontSize: 10, color: "#6b7280", marginLeft: "auto" }}>{fmtTime(m.created_at)}</span>}
                </div>
                {renderContent(m.content)}
              </div>
            ))}
          </div>
        )}

        {/* TOOL CALLS */}
        {tab === "tools" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {toolCalls.length === 0 && <div style={{ color: "#6b7280", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No tool calls in this run.</div>}
            {toolCalls.map((m, i) => {
              let parsed = null;
              try { parsed = typeof m.content === "string" ? JSON.parse(m.content) : m.content; } catch {}
              return (
                <div key={m.id || i} style={{ background: "#0f1117", borderRadius: 8, border: "1px solid #f59e0b33", overflow: "hidden" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: "#f59e0b0a", borderBottom: "1px solid #f59e0b22" }}>
                    <span style={{ fontSize: 13 }}>🔧</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: "#f59e0b" }}>{parsed?.tool || m.agent_name || "tool_call"}</span>
                    {m.agent_name && <span style={{ fontSize: 10, color: "#6b7280" }}>via {m.agent_name}</span>}
                    {m.created_at && <span style={{ fontSize: 10, color: "#6b7280", marginLeft: "auto" }}>{fmtTime(m.created_at)}</span>}
                  </div>
                  <div style={{ padding: "8px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
                    {parsed?.input != null && (
                      <div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Input</div>
                        <pre style={{ margin: 0, fontSize: 12, color: "#9ca3af", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{typeof parsed.input === "string" ? parsed.input : JSON.stringify(parsed.input, null, 2)}</pre>
                      </div>
                    )}
                    {parsed?.output != null && (
                      <div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#22c55e", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Result</div>
                        <pre style={{ margin: 0, fontSize: 12, color: "#d1d5db", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{typeof parsed.output === "string" ? parsed.output : JSON.stringify(parsed.output, null, 2)}</pre>
                      </div>
                    )}
                    {!parsed && renderContent(m.content)}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* STATS */}
        {tab === "stats" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10, paddingTop: 4 }}>
            {[
              { label: "Status", value: run.status, color: run.status === "completed" ? "#22c55e" : run.status === "failed" ? "#ef4444" : "#f59e0b" },
              { label: "Run ID", value: `#${run.id}` },
              { label: "Started", value: run.created_at ? new Date(run.created_at).toLocaleString() : "—" },
              { label: "Completed", value: run.completed_at ? new Date(run.completed_at).toLocaleString() : "—" },
              { label: "Duration", value: duration || "—", color: "#1affd5" },
              { label: "Total Messages", value: timeline.length },
              { label: "Agent Messages", value: agentMessages.length },
              { label: "Tool Calls", value: toolCalls.length, color: toolCalls.length > 0 ? "#f59e0b" : undefined },
              { label: "Total Tokens", value: run.total_tokens ? run.total_tokens.toLocaleString() : "—" },
              { label: "Est. Cost", value: cost || "—", color: "#22c55e" },
              { label: "Model", value: run.model || "—" },
              { label: "Agents", value: run.agent_count || nodes?.length || "—" },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ background: "#0f1117", borderRadius: 8, border: "1px solid #2d3348", padding: "10px 14px" }}>
                <div style={{ fontSize: 10, color: "#6b7280", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: color || "#e8e8e8" }}>{String(value)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   Scheduled Jobs Panel
───────────────────────────────────────────── */
function ScheduledJobsPanel() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState(null);

  async function loadJobs() {
    setLoading(true);
    try { const res = await axios.get(`${API_BASE}/workflows/scheduled-jobs`); setJobs(res.data); }
    catch { setJobs([]); }
    finally { setLoading(false); }
  }

  async function cancelJob(agentId) {
    if (!window.confirm("Cancel this scheduled job?")) return;
    setCancelling(agentId);
    try { await axios.delete(`${API_BASE}/workflows/scheduled-jobs/${agentId}`); await loadJobs(); }
    finally { setCancelling(null); }
  }

  useEffect(() => { loadJobs(); const iv = setInterval(loadJobs, 15000); return () => clearInterval(iv); }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#e8e8e8" }}>Scheduled Jobs</span>
        <button onClick={loadJobs} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #2d3348", background: "transparent", color: "#6b7280", cursor: "pointer" }}>{loading ? "↻" : "↻ Refresh"}</button>
      </div>
      {jobs.length === 0 && !loading && (
        <div style={{ textAlign: "center", padding: "20px 0" }}>
          <div style={{ fontSize: 24, marginBottom: 6 }}>🗓</div>
          <div style={{ fontSize: 12, color: "#6b7280" }}>No scheduled jobs active.</div>
          <div style={{ fontSize: 11, color: "#4b5563", marginTop: 4 }}>Ask the orchestrator to schedule a task</div>
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {jobs.map((job) => (
          <div key={job.job_id} style={{ background: "#0f1117", border: "1px solid #1affd530", borderRadius: 8, padding: "10px 12px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 10, background: "#1affd520", color: "#1affd5", border: "1px solid #1affd540", borderRadius: 3, padding: "1px 6px", fontWeight: 700 }}>CRON</span>
                  <code style={{ fontSize: 12, color: "#f59e0b", background: "#f59e0b15", borderRadius: 4, padding: "1px 6px" }}>{job.cron}</code>
                </div>
                <div style={{ fontWeight: 600, fontSize: 13, color: "#e8e8e8" }}>{job.agent_name}</div>
              </div>
              <button onClick={() => cancelJob(job.agent_id)} disabled={cancelling === job.agent_id} style={{ fontSize: 11, padding: "3px 8px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: cancelling === job.agent_id ? "#6b7280" : "#ef4444", cursor: "pointer" }}>{cancelling === job.agent_id ? "…" : "Cancel"}</button>
            </div>
            {job.prompt && <div style={{ fontSize: 12, color: "#9ca3af", background: "#1a1f2e", borderRadius: 5, padding: "5px 8px", marginTop: 6, overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{job.prompt}</div>}
            {job.next_run_utc && <div style={{ fontSize: 10, color: "#6b7280", marginTop: 6 }}>⏰ Next: {new Date(job.next_run_utc).toLocaleString()}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   App
───────────────────────────────────────────── */
export default function App() {
  const [agents, setAgents] = useState([]);
  const [runs, setRuns] = useState([]);
  const [messages, setMessages] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runError, setRunError] = useState("");
  const [editingAgent, setEditingAgent] = useState(null);
  const [bottomTab, setBottomTab] = useState("runs");

  const [templates, setTemplates] = useState([]);
  const [activeTemplateId, setActiveTemplateId] = useState(null);
  const [templateName, setTemplateName] = useState("");
  const [templateDesc, setTemplateDesc] = useState("");
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [templateMsg, setTemplateMsg] = useState("");

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const [agentForm, setAgentForm] = useState({
    name: "", role: "agent", system_prompt: "",
    model: "llama-3.3-70b-versatile",
    tools: [], channels: [], is_active: true,
    max_iterations: 5, memory_enabled: true, schedule: "",
    forbidden_topics: "", max_output_chars: "", skills: "",
  });

  const [workflowInput, setWorkflowInput] = useState(
    "Research the benefits of agent orchestration platforms for enterprise support."
  );

  const isOrchestratorForm = agentForm.role === "orchestrator";

  async function loadAgents() {
    const res = await axios.get(`${API_BASE}/agents`);
    const fetched = res.data;
    setAgents(fetched);
    return fetched;
  }

  async function loadRuns() {
    const res = await axios.get(`${API_BASE}/workflows/runs`);
    setRuns(res.data);
  }

  async function loadMessages(runId) {
    const res = await axios.get(`${API_BASE}/workflows/runs/${runId}/messages`);
    setMessages(res.data);
    setSelectedRunId(runId);
  }

  async function loadTemplates() {
    try { const res = await axios.get(`${API_BASE}/workflow-templates`); setTemplates(res.data); } catch {}
  }

  async function handleAgentSaved() {
    const fetched = await loadAgents();
    setNodes((nds) => nds.map((n) => {
      const updated = fetched.find((a) => String(a.id) === n.id);
      if (!updated) return n;
      return { ...n, data: { ...n.data, name: updated.name, role: updated.role, tools: parseList(updated.tools), channels: parseList(updated.channels) } };
    }));
  }

  async function createAgent(e) {
    e.preventDefault();
    const isOrch = agentForm.role === "orchestrator";
    let tools = agentForm.tools;
    if (isOrch) tools = [...new Set(["calculator", "datetime", ...tools])];
    const payload = {
      ...agentForm, tools,
      schedule: agentForm.schedule || null,
      forbidden_topics: agentForm.forbidden_topics ? agentForm.forbidden_topics.split(",").map((s) => s.trim()).filter(Boolean) : [],
      max_output_chars: agentForm.max_output_chars ? parseInt(agentForm.max_output_chars, 10) : null,
      channels: isOrch ? agentForm.channels : [],
      skills: agentForm.skills ? agentForm.skills.split(",").map((s) => s.trim()).filter(Boolean) : [],
    };
    await axios.post(`${API_BASE}/agents`, payload);
    setAgentForm({ name: "", role: "agent", system_prompt: "", model: "llama-3.3-70b-versatile", tools: [], channels: [], is_active: true, max_iterations: 5, memory_enabled: true, schedule: "", forbidden_topics: "", max_output_chars: "", skills: "" });
    await loadAgents();
  }

  async function deleteAgent(agentId) {
    if (!window.confirm("Delete this agent permanently?")) return;
    await axios.delete(`${API_BASE}/agents/${agentId}`);
    const id = String(agentId);
    setNodes((nds) => nds.filter((n) => n.id !== id));
    setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    await loadAgents();
  }

  function toggleTool(tool) {
    setAgentForm((f) => ({ ...f, tools: f.tools.includes(tool) ? f.tools.filter((t) => t !== tool) : [...f.tools, tool] }));
  }

  function toggleChannel(ch) {
    setAgentForm((f) => ({ ...f, channels: f.channels.includes(ch) ? f.channels.filter((c) => c !== ch) : [...f.channels, ch] }));
  }

  function addAgentToWorkflow(agent) {
    if (nodes.find((n) => n.id === String(agent.id))) return;
    const orchNode = nodes.find((n) => n.data.role === "orchestrator");
    const x = orchNode ? orchNode.position.x + 340 : 420;
    const y = 60 + nodes.filter((n) => n.id !== (orchNode?.id)).length * 160;
    setNodes((nds) => [...nds, { id: String(agent.id), type: "agentNode", position: { x, y }, data: { name: agent.name, role: agent.role, tools: parseList(agent.tools), channels: parseList(agent.channels), pending: true } }]);
  }

  function removeAgentFromWorkflow(agentId) {
    const id = String(agentId);
    setNodes((nds) => nds.filter((n) => n.id !== id));
    setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
  }

  const onConnect = useCallback((params) => {
    setNodes((nds) => nds.map((n) => n.id === params.target ? { ...n, data: { ...n.data, pending: false } } : n));
    setEdges((eds) => addEdge({ ...params, animated: true, style: { stroke: "#1affd5", strokeWidth: 2 } }, eds));
  }, [setEdges, setNodes]);

  async function saveTemplate() {
    if (!templateName.trim()) { setTemplateMsg("Please enter a workflow name."); return; }
    if (nodes.length < 2) { setTemplateMsg("Add at least 2 agents to the canvas."); return; }
    setSavingTemplate(true); setTemplateMsg("");
    try {
      await axios.post(`${API_BASE}/workflow-templates`, { name: templateName.trim(), description: templateDesc.trim() || null, agent_ids: nodes.map((n) => parseInt(n.id, 10)), edges: edges.map((e) => ({ source: e.source, target: e.target })) });
      setTemplateMsg(`✓ Saved "${templateName.trim()}"`);
      setTemplateName(""); setTemplateDesc("");
      await loadTemplates();
    } catch (err) {
      setTemplateMsg(err?.response?.data?.detail || "Failed to save template.");
    } finally { setSavingTemplate(false); }
  }

  async function loadTemplate(tpl) {
    const currentAgents = await loadAgents();
    let resolvedIds;
    if (tpl.is_builtin) {
      const nameToId = Object.fromEntries(currentAgents.map((a) => [a.name.toLowerCase(), a.id]));
      resolvedIds = tpl.agent_ids.map((nameOrId) => typeof nameOrId === "number" ? nameOrId : nameToId[String(nameOrId).toLowerCase()] ?? null).filter(Boolean);
    } else {
      resolvedIds = tpl.agent_ids;
    }
    if (!resolvedIds.length) { setTemplateMsg(`⚠ No matching agents found for "${tpl.name}".`); return; }
    const tplAgents = resolvedIds.map((id) => currentAgents.find((a) => a.id === id)).filter(Boolean);
    const { nodes: n, edges: e } = buildHubLayout(tplAgents);
    if (!tpl.is_builtin && tpl.edges?.length > 0) {
      const idSet = new Set(n.map((nd) => nd.id));
      const tplEdges = tpl.edges.filter((ed) => idSet.has(String(ed.source)) && idSet.has(String(ed.target))).map((ed) => ({ id: `e${ed.source}-${ed.target}`, source: String(ed.source), target: String(ed.target), animated: true, style: { stroke: "#1affd5", strokeWidth: 2 } }));
      setNodes(n); setEdges(tplEdges.length ? tplEdges : e);
    } else { setNodes(n); setEdges(e); }
    setActiveTemplateId(tpl.id);
    setTemplateMsg(`✓ Loaded "${tpl.name}"`);
    setTimeout(() => setTemplateMsg(""), 3000);
  }

  async function deleteTemplate(id) {
    if (!window.confirm("Delete this workflow template?")) return;
    try {
      await axios.delete(`${API_BASE}/workflow-templates/${id}`);
      if (activeTemplateId === id) { setActiveTemplateId(null); setNodes([]); setEdges([]); }
      await loadTemplates();
    } catch (err) { setTemplateMsg(err?.response?.data?.detail || "Failed to delete."); }
  }

  async function runWorkflow() {
    setRunError("");
    if (!nodes.some((n) => n.data.role === "orchestrator")) { setRunError("Add an Orchestrator agent to the canvas."); return; }
    if (nodes.length < 2) { setRunError("Add at least 2 agents (1 orchestrator + 1 specialist)."); return; }
    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/workflows/demo-run`, { user_input: workflowInput, agent_ids: nodes.map((n) => parseInt(n.id, 10)), edges: edges.map((e) => ({ source: e.source, target: e.target })) });
      await loadRuns();
      if (res.data?.schedule_intent) setBottomTab("scheduled");
    } catch (err) {
      setRunError(err?.response?.data?.detail || "Workflow run failed. Check backend logs.");
    } finally { setLoading(false); }
  }

  useEffect(() => { loadAgents(); loadRuns(); loadTemplates(); }, []);

  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws/monitor");
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      setLiveEvents((prev) => [data, ...prev].slice(0, 50));
    };
    return () => ws.close();
  }, []);

  const selectedRun = useMemo(() => runs.find((r) => r.id === selectedRunId), [runs, selectedRunId]);

  function btStyle(tab) {
    const active = bottomTab === tab;
    return {
      fontSize: 12, fontWeight: active ? 700 : 500,
      padding: "6px 14px", borderRadius: "6px 6px 0 0",
      border: active ? "1px solid #2d3348" : "1px solid transparent",
      borderBottom: active ? "1px solid #0f1117" : "1px solid transparent",
      background: active ? "#0f1117" : "transparent",
      color: active ? "#e8e8e8" : "#6b7280",
      cursor: "pointer", marginBottom: -1, transition: "color 0.15s",
    };
  }

  /* ── Run list card ── */
  function RunCard({ run }) {
    const isActive = run.id === selectedRunId;
    const statusColor = { completed: "#22c55e", failed: "#ef4444", running: "#f59e0b" }[run.status] || "#6b7280";
    const duration = fmtDuration(run.created_at, run.completed_at);
    const cost = fmtCost(run.total_tokens);

    return (
      <button
        onClick={() => loadMessages(run.id)}
        style={{
          width: "100%", textAlign: "left", background: isActive ? "rgba(26,255,213,0.06)" : "#0f1117",
          border: `1px solid ${isActive ? "#1affd560" : "#2d3348"}`,
          borderRadius: 8, padding: "10px 12px", cursor: "pointer", color: "#e8e8e8",
          transition: "border-color 0.15s, background 0.15s",
        }}
      >
        {/* Row 1: status + run id + time */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: statusColor, flexShrink: 0, display: "inline-block" }} />
          <span style={{ fontSize: 11, fontWeight: 700, color: statusColor }}>{run.status?.toUpperCase()}</span>
          <span style={{ fontSize: 11, color: "#6b7280" }}>#{run.id}</span>
          <span style={{ fontSize: 10, color: "#4b5563", marginLeft: "auto" }}>
            {run.created_at ? new Date(run.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
          </span>
        </div>
        {/* Row 2: input preview */}
        <div style={{ fontSize: 12, color: "#9ca3af", marginBottom: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>
          {run.input_text || "(no input)"}
        </div>
        {/* Row 3: metadata chips */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {run.total_tokens > 0 && (
            <span style={{ fontSize: 10, background: "#1a1f2e", color: "#6b7280", border: "1px solid #2d3348", borderRadius: 4, padding: "1px 6px" }}>
              {run.total_tokens.toLocaleString()} tok
            </span>
          )}
          {cost && (
            <span style={{ fontSize: 10, background: "#22c55e15", color: "#22c55e", border: "1px solid #22c55e30", borderRadius: 4, padding: "1px 6px" }}>
              {cost}
            </span>
          )}
          {duration && (
            <span style={{ fontSize: 10, background: "#1affd515", color: "#1affd5", border: "1px solid #1affd530", borderRadius: 4, padding: "1px 6px" }}>
              {duration}
            </span>
          )}
          {run.model && (
            <span style={{ fontSize: 10, background: "#1a1f2e", color: "#6b7280", border: "1px solid #2d3348", borderRadius: 4, padding: "1px 6px", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 120, whiteSpace: "nowrap", display: "inline-block" }}>
              {run.model}
            </span>
          )}
        </div>
      </button>
    );
  }

  return (
    <div className="app-shell">
      {editingAgent && (
        <EditAgentModal agent={editingAgent} onClose={() => setEditingAgent(null)} onSaved={handleAgentSaved} />
      )}

      {/* ════════════════ SIDEBAR ════════════════ */}
      <aside className="sidebar">
        <div style={{ paddingBottom: 10, borderBottom: "1px solid #1e2538" }}>
          <div className="eyebrow" style={{ marginBottom: 4 }}>Yuno Challenge</div>
          <h1 style={{ fontSize: "1.4rem", marginBottom: 4 }}>Agent Platform</h1>
          <p className="muted" style={{ fontSize: 12 }}>Build · Run · Monitor</p>
        </div>

        {/* ── Create Agent ── */}
        <SidebarSection title="Create Agent" defaultOpen={false}>
          <form onSubmit={createAgent} className="form-grid">
            <input placeholder="Agent name" value={agentForm.name} onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })} required />
            <div>
              <div className="muted-small" style={{ marginBottom: 4 }}>Role</div>
              <select value={agentForm.role} onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value, channels: [] })} style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
                <option value="agent">Agent</option>
                <option value="orchestrator">Orchestrator</option>
              </select>
            </div>
            <textarea placeholder="System prompt" rows={3} value={agentForm.system_prompt} onChange={(e) => setAgentForm({ ...agentForm, system_prompt: e.target.value })} required />
            <div>
              <div className="muted-small" style={{ marginBottom: 4 }}>Model</div>
              <select value={agentForm.model} onChange={(e) => setAgentForm({ ...agentForm, model: e.target.value })} style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
                {AVAILABLE_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Tools
                {isOrchestratorForm && <span style={{ marginLeft: 8, fontSize: 10, color: "#1affd5" }}>⚡ calculator &amp; datetime auto-included</span>}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {AVAILABLE_TOOLS.map((tool) => {
                  const isPinned = isOrchestratorForm && (tool === "calculator" || tool === "datetime");
                  return (
                    <label key={tool} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: isPinned ? "default" : "pointer", opacity: isPinned ? 0.7 : 1 }}>
                      <input type="checkbox" checked={isPinned ? true : agentForm.tools.includes(tool)} disabled={isPinned} onChange={() => !isPinned && toggleTool(tool)} />
                      {tool}{isPinned ? " 🔒" : ""}
                    </label>
                  );
                })}
              </div>
            </div>
            {isOrchestratorForm && (
              <div>
                <div className="muted-small" style={{ marginBottom: 6 }}>Channels <span style={{ color: "#f59e0b", fontSize: 10 }}>(orchestrator only)</span></div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {AVAILABLE_CHANNELS.map((ch) => (
                    <label key={ch} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                      <input type="checkbox" checked={agentForm.channels.includes(ch)} onChange={() => toggleChannel(ch)} />
                      {ch}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <input placeholder="Forbidden topics (comma-sep)" value={agentForm.forbidden_topics} onChange={(e) => setAgentForm({ ...agentForm, forbidden_topics: e.target.value })} />
            <input placeholder="Skills (comma-sep)" value={agentForm.skills} onChange={(e) => setAgentForm({ ...agentForm, skills: e.target.value })} />
            <button className="primary-btn" type="submit">Create agent</button>
          </form>
        </SidebarSection>

        {/* ── Agent Catalog ── */}
        <SidebarSection title="Agent Catalog" badge={agents.length} defaultOpen={true}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {agents.length === 0 && <div className="muted-small" style={{ fontSize: 11 }}>No agents yet. Create one above.</div>}
            {agents.map((agent) => {
              const tools = parseList(agent.tools);
              const channels = parseList(agent.channels);
              const inGraph = nodes.some((n) => n.id === String(agent.id));
              const isOrch = agent.role === "orchestrator";
              return (
                <div key={agent.id} style={{ background: "#0f1117", border: "1px solid #2d3348", borderRadius: 8, padding: "8px 10px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, marginBottom: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0, flex: 1 }}>
                      <strong style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{agent.name}</strong>
                      {isOrch && <span style={{ flexShrink: 0, fontSize: 9, background: "#f59e0b18", color: "#f59e0b", border: "1px solid #f59e0b35", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>ORCH</span>}
                      {agent.schedule && <span style={{ flexShrink: 0, fontSize: 9, background: "#8b5cf618", color: "#8b5cf6", border: "1px solid #8b5cf635", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>CRON</span>}
                    </div>
                    <div style={{ display: "flex", gap: 3, flexShrink: 0 }}>
                      <button onClick={() => setEditingAgent(agent)} title="Edit" style={{ fontSize: 11, padding: "2px 7px", borderRadius: 4, border: "1px solid #2d3348", background: "transparent", color: "#6b7280", cursor: "pointer" }}>✎</button>
                      {inGraph
                        ? <button onClick={() => removeAgentFromWorkflow(agent.id)} style={{ fontSize: 11, padding: "2px 7px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: "#ef4444", cursor: "pointer" }}>— canvas</button>
                        : <button onClick={() => addAgentToWorkflow(agent)} style={{ fontSize: 11, padding: "2px 7px", borderRadius: 4, border: "1px solid #1affd530", background: "transparent", color: "#1affd5", cursor: "pointer" }}>+ canvas</button>
                      }
                      <button onClick={() => deleteAgent(agent.id)} title="Delete" style={{ fontSize: 11, padding: "2px 7px", borderRadius: 4, border: "1px solid #ef444420", background: "transparent", color: "#ef444480", cursor: "pointer" }}>🗑</button>
                    </div>
                  </div>
                  <div style={{ fontSize: 10, color: "#6b7280", marginBottom: tools.length ? 4 : 0 }}>{agent.model}</div>
                  {tools.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                      {tools.map((t) => {
                        const isPinned = isOrch && (t === "calculator" || t === "datetime");
                        return <span key={t} style={{ background: isPinned ? "#1affd515" : "#f59e0b15", color: isPinned ? "#1affd5" : "#f59e0b", border: `1px solid ${isPinned ? "#1affd530" : "#f59e0b30"}`, borderRadius: 3, fontSize: 9, padding: "1px 4px" }}>{isPinned ? "⚡" : "🔧"}{t}</span>;
                      })}
                      {channels.map((c) => <span key={c} style={{ background: "#0ea5e915", color: "#0ea5e9", border: "1px solid #0ea5e930", borderRadius: 3, fontSize: 9, padding: "1px 4px" }}>📡{c}</span>)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </SidebarSection>

        {/* ── Templates ── */}
        <SidebarSection title="Workflow Templates" badge={templates.length} defaultOpen={true}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
            {templates.length === 0 && <div className="muted-small" style={{ fontSize: 11 }}>No templates saved yet.</div>}
            {templates.map((tpl) => (
              <div key={tpl.id} style={{ background: "#0f1117", border: `1px solid ${activeTemplateId === tpl.id ? "#1affd560" : "#2d3348"}`, borderRadius: 7, padding: "7px 10px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, fontWeight: 600, color: "#e8e8e8" }}>
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{tpl.name}</span>
                      {tpl.is_builtin && <span style={{ flexShrink: 0, fontSize: 9, background: "#f59e0b18", color: "#f59e0b", border: "1px solid #f59e0b35", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>BUILT-IN</span>}
                      {activeTemplateId === tpl.id && <span style={{ flexShrink: 0, fontSize: 9, background: "#1affd518", color: "#1affd5", border: "1px solid #1affd535", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>ACTIVE</span>}
                    </div>
                    {tpl.description && <div className="muted-small" style={{ fontSize: 10, marginTop: 2 }}>{tpl.description}</div>}
                  </div>
                  <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                    <button onClick={() => loadTemplate(tpl)} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 4, border: "1px solid #1affd530", background: "transparent", color: "#1affd5", cursor: "pointer" }}>Load</button>
                    {!tpl.is_builtin && <button onClick={() => deleteTemplate(tpl.id)} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: "#ef4444", cursor: "pointer" }}>Del</button>}
                  </div>
                </div>
              </div>
            ))}
          </div>
          {templateMsg && <div style={{ fontSize: 11, color: templateMsg.startsWith("✓") ? "#22c55e" : "#f87171", marginBottom: 8, padding: "4px 8px", background: templateMsg.startsWith("✓") ? "#22c55e15" : "#f8717115", borderRadius: 5 }}>{templateMsg}</div>}
          <div className="form-grid">
            <input placeholder="Workflow name" value={templateName} onChange={(e) => setTemplateName(e.target.value)} />
            <input placeholder="Description (optional)" value={templateDesc} onChange={(e) => setTemplateDesc(e.target.value)} />
            <button className="primary-btn" onClick={saveTemplate} disabled={savingTemplate} style={{ padding: "8px 12px", fontSize: 12 }}>{savingTemplate ? "Saving..." : "Save current canvas"}</button>
          </div>
        </SidebarSection>
      </aside>

      {/* ════════════════ MAIN ════════════════ */}
      <main className="main">

        {/* ── Canvas + Run Panel ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 16, height: "calc(100vh - 300px)", minHeight: 400 }}>

          {/* ReactFlow Canvas */}
          <div className="panel" style={{ padding: 0, overflow: "hidden", position: "relative" }}>
            <div style={{ position: "absolute", top: 10, left: 12, zIndex: 10 }}>
              <div className="eyebrow">Visual Builder</div>
              <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>Drag to reposition · Connect handles to wire agents</div>
            </div>
            {nodes.length === 0 && (
              <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 5, pointerEvents: "none" }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>🕸</div>
                <div className="muted-small" style={{ fontSize: 13 }}>Canvas is empty</div>
                <div className="muted-small" style={{ fontSize: 11, marginTop: 4 }}>Load a template or add agents from the sidebar</div>
              </div>
            )}
            <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.3 }} style={{ background: "#0a0d14" }}>
              <Background color="#1a1f2e" gap={20} />
              <Controls style={{ background: "#1a1f2e", border: "1px solid #2d3348" }} />
              <MiniMap nodeColor={(n) => n.data.role === "orchestrator" ? "#f59e0b" : "#1affd5"} style={{ background: "#0f1117", border: "1px solid #2d3348" }} />
            </ReactFlow>
          </div>

          {/* Run Panel */}
          <div className="panel" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <div className="eyebrow">Execute</div>
              <h2>Run Workflow</h2>
            </div>
            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Canvas agents ({nodes.length})</div>
              {nodes.length === 0
                ? <div className="muted-small" style={{ fontSize: 11 }}>No agents on canvas yet.</div>
                : (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 4 }}>
                    {nodes.map((n) => (
                      <span key={n.id} style={{ fontSize: 11, background: n.data.role === "orchestrator" ? "#f59e0b18" : "#1affd518", color: n.data.role === "orchestrator" ? "#f59e0b" : "#1affd5", border: `1px solid ${n.data.role === "orchestrator" ? "#f59e0b40" : "#1affd540"}`, borderRadius: 4, padding: "2px 8px" }}>
                        {n.data.name}
                      </span>
                    ))}
                  </div>
                )
              }
            </div>
            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Input message</div>
              <textarea rows={4} value={workflowInput} onChange={(e) => setWorkflowInput(e.target.value)} style={{ fontSize: 12 }} />
            </div>
            <button className="primary-btn" onClick={runWorkflow} disabled={loading || nodes.length === 0}>
              {loading ? "Running…" : "▶ Run Workflow"}
            </button>
            {runError && <div style={{ fontSize: 12, color: "#f87171", padding: "6px 10px", background: "#f8717115", borderRadius: 6, border: "1px solid #f8717130" }}>⚠ {runError}</div>}
          </div>
        </div>

        {/* ════════════════ BOTTOM PANEL ════════════════ */}
        <div className="panel" style={{ marginTop: 16, display: "flex", flexDirection: "column", minHeight: 0, height: selectedRunId ? 460 : 280 }}>

          {/* Bottom tab bar */}
          <div style={{ display: "flex", gap: 2, borderBottom: "1px solid #2d3348", flexShrink: 0, paddingBottom: 0 }}>
            <button style={btStyle("runs")} onClick={() => setBottomTab("runs")}>Run History ({runs.length})</button>
            <button style={btStyle("monitor")} onClick={() => setBottomTab("monitor")}>Live Monitor {liveEvents.length > 0 && <span style={{ marginLeft: 4, fontSize: 10, background: "#1affd520", color: "#1affd5", borderRadius: 9, padding: "0 5px" }}>{liveEvents.length}</span>}</button>
            <button style={btStyle("scheduled")} onClick={() => setBottomTab("scheduled")}>Scheduled Jobs</button>
          </div>

          {/* ── RUN HISTORY tab ── */}
          {bottomTab === "runs" && (
            <div style={{ display: "grid", gridTemplateColumns: selectedRunId ? "280px 1fr" : "1fr", gap: 0, flex: 1, minHeight: 0 }}>

              {/* Run list */}
              <div style={{ borderRight: selectedRunId ? "1px solid #2d3348" : "none", overflowY: "auto", padding: "10px 10px 10px 0", display: "flex", flexDirection: "column", gap: 6 }}>
                {runs.length === 0 && (
                  <div style={{ textAlign: "center", paddingTop: 24 }}>
                    <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
                    <div className="muted-small" style={{ fontSize: 12 }}>No runs yet. Load a template and hit Run.</div>
                  </div>
                )}
                {runs.map((run) => <RunCard key={run.id} run={run} />)}
              </div>

              {/* Run detail */}
              {selectedRun && messages.length >= 0 && (
                <RunDetailPanel
                  run={selectedRun}
                  messages={messages}
                  nodes={nodes}
                  onClose={() => setSelectedRunId(null)}
                />
              )}
            </div>
          )}

          {/* ── LIVE MONITOR tab ── */}
          {bottomTab === "monitor" && (
            <div style={{ flex: 1, overflowY: "auto", padding: "10px 0" }}>
              {liveEvents.length === 0 && (
                <div style={{ textAlign: "center", paddingTop: 24 }}>
                  <div style={{ fontSize: 24, marginBottom: 8 }}>📡</div>
                  <div className="muted-small" style={{ fontSize: 12 }}>Listening for live events…</div>
                </div>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {liveEvents.map((evt, i) => (
                  <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "6px 8px", background: i === 0 ? "#1affd50a" : "transparent", borderRadius: 5, borderBottom: "1px solid #1e2538" }}>
                    <span style={{ fontSize: 10, color: "#6b7280", flexShrink: 0, marginTop: 2, fontFamily: "monospace" }}>{fmtTime(evt.timestamp || evt.created_at)}</span>
                    <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 3, background: ({ input: "#0ea5e9", output: "#22c55e", tool_call: "#f59e0b", agent_message: "#8b5cf6" }[evt.type] || "#6b7280") + "22", color: ({ input: "#0ea5e9", output: "#22c55e", tool_call: "#f59e0b", agent_message: "#8b5cf6" }[evt.type] || "#6b7280"), flexShrink: 0 }}>{evt.type || "event"}</span>
                    {evt.agent && <span style={{ fontSize: 10, color: "#f59e0b", fontWeight: 600, flexShrink: 0 }}>{evt.agent}</span>}
                    <span style={{ fontSize: 11, color: "#9ca3af", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                      {typeof evt.content === "string" ? evt.content : JSON.stringify(evt.content)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── SCHEDULED JOBS tab ── */}
          {bottomTab === "scheduled" && (
            <div style={{ flex: 1, overflowY: "auto", padding: "10px 0" }}>
              <ScheduledJobsPanel />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
