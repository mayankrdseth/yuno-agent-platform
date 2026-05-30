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
   Custom Node
───────────────────────────────────────────── */
function CustomAgentNode({ data }) {
  const tools = data.tools || [];
  const channels = data.channels || [];
  const visibleTools = tools.slice(0, 3);
  const extraTools = tools.length - visibleTools.length;
  const isOrchestrator = data.role === "orchestrator";

  return (
    <div style={{
      background: "#1a1f2e",
      border: isOrchestrator
        ? "1.5px solid #f59e0b"
        : data.pending ? "2px dashed #1affd5" : "1px solid #2d3348",
      borderRadius: 10,
      padding: "10px 14px",
      minWidth: 180,
      maxWidth: 220,
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
      {visibleTools.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3, marginBottom: 4 }}>
          {visibleTools.map((t) => (
            <span key={t} style={{ background: "#f59e0b22", color: "#f59e0b", border: "1px solid #f59e0b44", borderRadius: 4, fontSize: 10, padding: "1px 5px", fontWeight: 600 }}>🔧 {t}</span>
          ))}
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
      const payload = {
        ...form,
        forbidden_topics: form.forbidden_topics
          ? form.forbidden_topics.split(",").map((s) => s.trim()).filter(Boolean)
          : [],
        max_output_chars: form.max_output_chars ? parseInt(form.max_output_chars, 10) : null,
        channels: isOrch ? form.channels : [],
      };
      await axios.patch(`${API_BASE}/agents/${agent.id}`, payload);
      onSaved();
      onClose();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save changes.");
    } finally { setSaving(false); }
  }

  function handleBackdrop(e) { if (e.target === e.currentTarget) onClose(); }

  return (
    <div onClick={handleBackdrop} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, backdropFilter: "blur(4px)",
    }}>
      <div style={{
        background: "#1a1f2e", border: "1px solid #2d3348", borderRadius: 12,
        padding: 24, width: "min(560px, 95vw)", maxHeight: "90vh",
        overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 10, color: "#1affd5", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>Edit Agent</div>
            <div style={{ fontWeight: 700, fontSize: 16, color: "#e8e8e8" }}>{agent.name}</div>
          </div>
          <button onClick={onClose} style={{ background: "transparent", border: "none", color: "#6b7280", fontSize: 20, cursor: "pointer", lineHeight: 1, padding: "2px 6px" }}>✕</button>
        </div>

        <div className="form-grid">
          <div>
            <div className="muted-small" style={{ marginBottom: 4 }}>Name</div>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <div className="muted-small" style={{ marginBottom: 4 }}>Role</div>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value, channels: [] })}
              style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
              <option value="agent">Agent</option>
              <option value="orchestrator">Orchestrator</option>
            </select>
          </div>
          <div>
            <div className="muted-small" style={{ marginBottom: 4 }}>System Prompt</div>
            <textarea rows={5} value={form.system_prompt}
              onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
              style={{ resize: "vertical" }} />
          </div>
          <div>
            <div className="muted-small" style={{ marginBottom: 4 }}>Model</div>
            <select value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}
              style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
              {AVAILABLE_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <div className="muted-small" style={{ marginBottom: 6 }}>Tools</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {AVAILABLE_TOOLS.map((tool) => (
                <label key={tool} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                  <input type="checkbox" checked={form.tools.includes(tool)} onChange={() => toggleTool(tool)} />
                  {tool}
                </label>
              ))}
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
          <div>
            <div className="muted-small" style={{ marginBottom: 4 }}>Forbidden Topics <span style={{ color: "#6b7280", fontSize: 10 }}>(comma-separated)</span></div>
            <input value={form.forbidden_topics} onChange={(e) => setForm({ ...form, forbidden_topics: e.target.value })} placeholder="e.g. violence, politics" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div>
              <div className="muted-small" style={{ marginBottom: 4 }}>Max Iterations</div>
              <input type="number" min={1} max={20} value={form.max_iterations}
                onChange={(e) => setForm({ ...form, max_iterations: Number(e.target.value) })} />
            </div>
            <div>
              <div className="muted-small" style={{ marginBottom: 4 }}>Max Output Chars</div>
              <input type="number" value={form.max_output_chars}
                onChange={(e) => setForm({ ...form, max_output_chars: e.target.value })} placeholder="optional" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              Active
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" checked={form.memory_enabled} onChange={(e) => setForm({ ...form, memory_enabled: e.target.checked })} />
              Memory enabled
            </label>
          </div>
        </div>

        {error && (
          <div style={{ color: "#f87171", fontSize: 12, marginTop: 12, padding: "6px 10px", background: "#f8717115", borderRadius: 6, border: "1px solid #f8717130" }}>⚠ {error}</div>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 20, justifyContent: "flex-end" }}>
          <button onClick={onClose}
            style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #2d3348", background: "transparent", color: "#6b7280", cursor: "pointer", fontSize: 13 }}>
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className="primary-btn" style={{ padding: "8px 20px", fontSize: 13 }}>
            {saving ? "Saving..." : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

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
    data: { name: agent.name, role: agent.role, tools: parseList(agent.tools), channels: parseList(agent.channels), pending: false },
  };
}

function buildHubLayout(agents) {
  if (!agents.length) return { nodes: [], edges: [] };
  const orch = agents.find((a) => a.role === "orchestrator");
  if (!orch) {
    const nodes = agents.map((a, i) => buildAgentNode(a, { x: 80 + i * 280, y: 160 }));
    const edges = agents.slice(0, -1).map((a, i) => ({
      id: `e${a.id}-${agents[i + 1].id}`, source: String(a.id), target: String(agents[i + 1].id),
      animated: true, style: { stroke: "#1affd5", strokeWidth: 2 },
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
    id: `e${orch.id}-${a.id}`, source: String(orch.id), target: String(a.id),
    animated: true, style: { stroke: "#f59e0b80", strokeWidth: 1.5, strokeDasharray: "5 3" },
  }));
  return { nodes, edges };
}

function MessageTypeTag({ type }) {
  const colours = { input: "#0ea5e9", output: "#22c55e", log: "#6b7280", agent_message: "#8b5cf6", tool_call: "#f59e0b" };
  return (
    <span style={{ background: colours[type] || "#6b7280", color: "#fff", borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 600 }}>{type}</span>
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
    try {
      const res = await axios.get(`${API_BASE}/workflows/scheduled-jobs`);
      setJobs(res.data);
    } catch {
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }

  async function cancelJob(agentId) {
    if (!window.confirm("Cancel this scheduled job?")) return;
    setCancelling(agentId);
    try {
      await axios.delete(`${API_BASE}/workflows/scheduled-jobs/${agentId}`);
      await loadJobs();
    } finally {
      setCancelling(null);
    }
  }

  useEffect(() => {
    loadJobs();
    const interval = setInterval(loadJobs, 15000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="panel" style={{ height: "100%" }}>
      <div className="panel-header">
        <div>
          <div className="eyebrow">Automation</div>
          <h2>Scheduled Jobs</h2>
        </div>
        <button
          onClick={loadJobs}
          style={{ fontSize: 11, padding: "4px 10px", borderRadius: 4, border: "1px solid #2d3348", background: "transparent", color: "#6b7280", cursor: "pointer" }}
        >
          {loading ? "Refreshing..." : "↻ Refresh"}
        </button>
      </div>

      {jobs.length === 0 && !loading && (
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <div style={{ fontSize: 28, marginBottom: 8 }}>🗓</div>
          <div className="muted-small" style={{ fontSize: 12 }}>No scheduled jobs active.</div>
          <div className="muted-small" style={{ fontSize: 11, marginTop: 4, maxWidth: 260, margin: "4px auto 0" }}>
            Ask the orchestrator to schedule a task — e.g. <em>"Search for AI news every morning at 9am"</em>
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {jobs.map((job) => (
          <div key={job.job_id} style={{
            background: "#0f1117",
            border: "1px solid #1affd530",
            borderRadius: 8,
            padding: "12px 14px",
            position: "relative",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 10, background: "#1affd520", color: "#1affd5", border: "1px solid #1affd540", borderRadius: 3, padding: "1px 6px", fontWeight: 700, letterSpacing: "0.05em" }}>CRON</span>
                  <code style={{ fontSize: 12, color: "#f59e0b", background: "#f59e0b15", borderRadius: 4, padding: "1px 6px" }}>{job.cron}</code>
                </div>
                <div style={{ fontWeight: 600, fontSize: 13, color: "#e8e8e8", marginBottom: 2 }}>{job.agent_name}</div>
                <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>agent_id: {job.agent_id}</div>
              </div>
              <button
                onClick={() => cancelJob(job.agent_id)}
                disabled={cancelling === job.agent_id}
                style={{
                  flexShrink: 0,
                  fontSize: 11, padding: "4px 10px", borderRadius: 4,
                  border: "1px solid #ef444430", background: "transparent",
                  color: cancelling === job.agent_id ? "#6b7280" : "#ef4444",
                  cursor: cancelling === job.agent_id ? "default" : "pointer",
                }}
              >
                {cancelling === job.agent_id ? "Cancelling..." : "Cancel"}
              </button>
            </div>

            {job.prompt ? (
              <div style={{
                fontSize: 12, color: "#9ca3af",
                background: "#1a1f2e", borderRadius: 5,
                padding: "6px 8px", marginBottom: 6,
                overflow: "hidden", textOverflow: "ellipsis",
                display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
              }}>
                {job.prompt}
              </div>
            ) : null}

            {job.next_run_utc ? (
              <div style={{ fontSize: 10, color: "#6b7280", display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ color: "#22c55e" }}>⏰</span>
                Next run: {new Date(job.next_run_utc).toLocaleString()}
              </div>
            ) : null}
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
    tools: [], channels: [],
    is_active: true, max_iterations: 5,
    memory_enabled: true, schedule: "",
    forbidden_topics: "", max_output_chars: "",
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
    try {
      const res = await axios.get(`${API_BASE}/workflow-templates`);
      setTemplates(res.data);
    } catch {
      // silently ignore
    }
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
    const payload = {
      ...agentForm,
      schedule: agentForm.schedule || null,
      forbidden_topics: agentForm.forbidden_topics
        ? agentForm.forbidden_topics.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
      max_output_chars: agentForm.max_output_chars ? parseInt(agentForm.max_output_chars, 10) : null,
      channels: isOrchestratorForm ? agentForm.channels : [],
    };
    await axios.post(`${API_BASE}/agents`, payload);
    setAgentForm({
      name: "", role: "agent", system_prompt: "",
      model: "llama-3.3-70b-versatile",
      tools: [], channels: [],
      is_active: true, max_iterations: 5,
      memory_enabled: true, schedule: "",
      forbidden_topics: "", max_output_chars: "",
    });
    await loadAgents();
  }

  async function deleteAgent(agentId) {
    if (!window.confirm("Delete this agent from the database permanently?")) return;
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
    setNodes((nds) => [...nds, {
      id: String(agent.id), type: "agentNode",
      position: { x, y },
      data: { name: agent.name, role: agent.role, tools: parseList(agent.tools), channels: parseList(agent.channels), pending: true },
    }]);
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
    if (nodes.length < 2) { setTemplateMsg("Add at least 2 agents to the canvas before saving."); return; }
    setSavingTemplate(true); setTemplateMsg("");
    try {
      const agent_ids = nodes.map((n) => parseInt(n.id, 10));
      const edgesPayload = edges.map((e) => ({ source: e.source, target: e.target }));
      await axios.post(`${API_BASE}/workflow-templates`, {
        name: templateName.trim(), description: templateDesc.trim() || null, agent_ids, edges: edgesPayload,
      });
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
      resolvedIds = tpl.agent_ids
        .map((nameOrId) => typeof nameOrId === "number" ? nameOrId : nameToId[String(nameOrId).toLowerCase()] ?? null)
        .filter(Boolean);
    } else {
      resolvedIds = tpl.agent_ids;
    }
    if (!resolvedIds.length) {
      setTemplateMsg(`⚠ No matching agents found for "${tpl.name}". Create the agents first.`);
      return;
    }
    const tplAgents = resolvedIds.map((id) => currentAgents.find((a) => a.id === id)).filter(Boolean);
    const { nodes: n, edges: e } = buildHubLayout(tplAgents);
    if (!tpl.is_builtin && tpl.edges && tpl.edges.length > 0) {
      const idSet = new Set(n.map((nd) => nd.id));
      const tplEdges = tpl.edges
        .filter((ed) => idSet.has(String(ed.source)) && idSet.has(String(ed.target)))
        .map((ed) => ({ id: `e${ed.source}-${ed.target}`, source: String(ed.source), target: String(ed.target), animated: true, style: { stroke: "#1affd5", strokeWidth: 2 } }));
      setNodes(n); setEdges(tplEdges.length ? tplEdges : e);
    } else {
      setNodes(n); setEdges(e);
    }
    setActiveTemplateId(tpl.id);
    setTemplateMsg(`✓ Loaded "${tpl.name}" onto canvas.`);
    setTimeout(() => setTemplateMsg(""), 3000);
  }

  async function deleteTemplate(id) {
    if (!window.confirm("Delete this workflow template?")) return;
    try {
      await axios.delete(`${API_BASE}/workflow-templates/${id}`);
      if (activeTemplateId === id) {
        setActiveTemplateId(null);
        setNodes([]); setEdges([]);
      }
      await loadTemplates();
    } catch (err) {
      setTemplateMsg(err?.response?.data?.detail || "Failed to delete template.");
    }
  }

  async function runWorkflow() {
    setRunError("");
    const hasOrch = nodes.some((n) => n.data.role === "orchestrator");
    if (!hasOrch) { setRunError("Add an Orchestrator agent to the canvas before running."); return; }
    if (nodes.length < 2) { setRunError("Add at least 2 agents (1 orchestrator + 1 specialist) to the canvas."); return; }
    setLoading(true);
    try {
      const agent_ids = nodes.map((n) => parseInt(n.id, 10));
      const edgePayload = edges.map((e) => ({ source: e.source, target: e.target }));
      const res = await axios.post(`${API_BASE}/workflows/demo-run`, { user_input: workflowInput, agent_ids, edges: edgePayload });
      await loadRuns();
      if (res.data?.schedule_intent) {
        setBottomTab("scheduled");
      }
    } catch (err) {
      setRunError(err?.response?.data?.detail || "Workflow run failed. Check backend logs.");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    loadAgents();
    loadRuns();
    loadTemplates();
  }, []);

  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws/monitor");
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      setLiveEvents((prev) => [data, ...prev].slice(0, 30));
    };
    return () => ws.close();
  }, []);

  const selectedRun = useMemo(() => runs.find((r) => r.id === selectedRunId), [runs, selectedRunId]);

  function tabStyle(tab) {
    const active = bottomTab === tab;
    return {
      fontSize: 12, fontWeight: active ? 700 : 500,
      padding: "6px 14px", borderRadius: "6px 6px 0 0",
      border: active ? "1px solid #2d3348" : "1px solid transparent",
      borderBottom: active ? "1px solid #0f1117" : "1px solid transparent",
      background: active ? "#0f1117" : "transparent",
      color: active ? "#e8e8e8" : "#6b7280",
      cursor: "pointer",
      marginBottom: -1,
      transition: "color 0.15s",
    };
  }

  return (
    <div className="app-shell">
      {editingAgent ? (
        <EditAgentModal
          agent={editingAgent}
          onClose={() => setEditingAgent(null)}
          onSaved={handleAgentSaved}
        />
      ) : null}

      <aside className="sidebar">
        <div>
          <div className="eyebrow">Yuno Challenge</div>
          <h1>Agent Orchestration Platform</h1>
          <p className="muted">Manage agents, run workflows, inspect history, and monitor live events.</p>
        </div>

        {/* ── Create Agent ── */}
        <section className="panel">
          <h2>Create Agent</h2>
          <form onSubmit={createAgent} className="form-grid">
            <input placeholder="Agent name" value={agentForm.name}
              onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })} required />
            <div>
              <div className="muted-small" style={{ marginBottom: 4 }}>Role</div>
              <select value={agentForm.role}
                onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value, channels: [] })}
                style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
                <option value="agent">Agent</option>
                <option value="orchestrator">Orchestrator</option>
              </select>
            </div>
            <textarea placeholder="System prompt" rows="4" value={agentForm.system_prompt}
              onChange={(e) => setAgentForm({ ...agentForm, system_prompt: e.target.value })} required />
            <div>
              <div className="muted-small" style={{ marginBottom: 4 }}>Model</div>
              <select value={agentForm.model}
                onChange={(e) => setAgentForm({ ...agentForm, model: e.target.value })}
                style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
                {AVAILABLE_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Tools</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {AVAILABLE_TOOLS.map((tool) => (
                  <label key={tool} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={agentForm.tools.includes(tool)} onChange={() => toggleTool(tool)} />
                    {tool}
                  </label>
                ))}
              </div>
            </div>
            {isOrchestratorForm ? (
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
            ) : null}
            <input placeholder="Forbidden topics (comma-separated)" value={agentForm.forbidden_topics}
              onChange={(e) => setAgentForm({ ...agentForm, forbidden_topics: e.target.value })} />
            <input type="number" placeholder="Max output chars (optional)" value={agentForm.max_output_chars}
              onChange={(e) => setAgentForm({ ...agentForm, max_output_chars: e.target.value })} />
            <input type="number" min="1" max="20" placeholder="Max iterations"
              value={agentForm.max_iterations}
              onChange={(e) => setAgentForm({ ...agentForm, max_iterations: Number(e.target.value) })} />
            <button className="primary-btn" type="submit">Create agent</button>
          </form>
        </section>

        {/* ── Agent List ── */}
        <section className="panel">
          <h2>Agents <span className="muted-small" style={{ fontWeight: 400, fontSize: 11 }}>(catalog)</span></h2>
          <div className="list">
            {agents.map((agent) => {
              const tools = parseList(agent.tools);
              const channels = parseList(agent.channels);
              const inGraph = nodes.some((n) => n.id === String(agent.id));
              const isOrch = agent.role === "orchestrator";
              return (
                <div className="list-item" key={agent.id} style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
                  <div style={{ display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center", gap: 8, minWidth: 0 }}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
                        <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0, display: "block" }}>{agent.name}</strong>
                        {isOrch ? (
                          <span style={{ flexShrink: 0, fontSize: 9, background: "#f59e0b18", color: "#f59e0b", border: "1px solid #f59e0b35", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>ORCH</span>
                        ) : null}
                        {agent.schedule ? (
                          <span title={`Scheduled: ${agent.schedule}`} style={{ flexShrink: 0, fontSize: 9, background: "#22c55e18", color: "#22c55e", border: "1px solid #22c55e35", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>⏰ SCHED</span>
                        ) : null}
                      </div>
                      <div className="muted-small">{agent.role} · {agent.model?.split("-")[0] ?? ""}</div>
                    </div>
                    <div style={{ display: "flex", gap: 5, flexShrink: 0 }}>
                      <button onClick={() => setEditingAgent(agent)} title="Edit agent"
                        style={{ fontSize: 13, padding: "3px 8px", borderRadius: 4, border: "1px solid #1affd530", background: "transparent", color: "#1affd5", cursor: "pointer" }}>
                        ✏
                      </button>
                      {!inGraph ? (
                        <button onClick={() => addAgentToWorkflow(agent)}
                          style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #1affd5", background: "transparent", color: "#1affd5", cursor: "pointer", whiteSpace: "nowrap" }}>
                          + Add
                        </button>
                      ) : (
                        <button onClick={() => removeAgentFromWorkflow(agent.id)}
                          style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #f87171", background: "transparent", color: "#f87171", cursor: "pointer", whiteSpace: "nowrap" }}>
                          − Remove
                        </button>
                      )}
                      <button onClick={() => deleteAgent(agent.id)} title="Delete from database"
                        style={{ fontSize: 13, padding: "3px 8px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: "#ef4444", cursor: "pointer" }}>
                        🗑
                      </button>
                    </div>
                  </div>
                  {tools.length > 0 ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {tools.map((t) => <span key={t} className="badge" style={{ background: "#f59e0b20", color: "#f59e0b", fontSize: 10 }}>🔧 {t}</span>)}
                    </div>
                  ) : null}
                  {channels.length > 0 ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {channels.map((c) => <span key={c} className="badge" style={{ background: "#0ea5e920", color: "#0ea5e9", fontSize: 10 }}>📡 {c}</span>)}
                    </div>
                  ) : null}
                </div>
              );
            })}
            {agents.length === 0 ? <div className="muted-small">No agents yet.</div> : null}
          </div>
        </section>
      </aside>

      <main className="main-content">
        <section className="top-grid">

          {/* ── Visual Workflow Builder ── */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="eyebrow">Workflow</div>
                <h2>Visual Builder</h2>
              </div>
              <div className="muted-small" style={{ fontSize: 11, marginTop: 4 }}>
                Drag handles to connect · Select + Delete removes edge/node · Only canvas agents run
              </div>
            </div>
            <div className="flow-wrap">
              <ReactFlow
                nodes={nodes} edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                deleteKeyCode="Delete"
                fitView
              >
                <Background color="#2d3348" gap={20} />
                <Controls />
                <MiniMap nodeColor={(n) => n.data?.role === "orchestrator" ? "#f59e0b" : "#1a1f2e"}
                  maskColor="rgba(10,12,20,0.7)"
                  style={{ background: "#0f1117", border: "1px solid #2d3348" }} />
              </ReactFlow>
            </div>
          </div>

          {/* ── Right column: Run + Templates ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Run Workflow */}
            <div className="panel">
              <div className="eyebrow">Execution</div>
              <h2>Run Workflow</h2>
              <div className="muted-small" style={{ marginBottom: 8, fontSize: 11 }}>
                Runs only the {nodes.length} agent{nodes.length !== 1 ? "s" : ""} currently on the canvas.
                {!nodes.some((n) => n.data.role === "orchestrator") && nodes.length > 0 ? (
                  <span style={{ color: "#f59e0b", marginLeft: 6 }}>⚠ No orchestrator on canvas.</span>
                ) : null}
              </div>
              <textarea rows="4" value={workflowInput} onChange={(e) => setWorkflowInput(e.target.value)} />
              {runError ? (
                <div style={{ color: "#f87171", fontSize: 12, marginTop: 6, padding: "6px 10px", background: "#f8717115", borderRadius: 6, border: "1px solid #f8717130" }}>⚠ {runError}</div>
              ) : null}
              <button className="primary-btn" onClick={runWorkflow} disabled={loading} style={{ marginTop: 10 }}>
                {loading ? "Running..." : `Run workflow (${nodes.length} agents)`}
              </button>
            </div>

            {/* Workflow Templates */}
            <div className="panel">
              <div className="eyebrow">Templates</div>
              <h2>Workflow Templates</h2>
              <div style={{ marginBottom: 12 }}>
                <div className="muted-small" style={{ marginBottom: 6, fontSize: 11 }}>Load onto canvas</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {templates.map((tpl) => {
                    const isActive = tpl.id === activeTemplateId;
                    const builtinBadge = tpl.is_builtin === 1
                      ? <span style={{ flexShrink: 0, fontSize: 9, background: "#1affd520", color: "#1affd5", border: "1px solid #1affd540", borderRadius: 3, padding: "1px 5px" }}>BUILT-IN</span>
                      : null;
                    return (
                      <div key={tpl.id} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        background: isActive ? "#1affd508" : "#0f1117",
                        borderRadius: 6, padding: "7px 10px",
                        border: isActive ? "1px solid #1affd540" : "1px solid #2d3348",
                        transition: "border-color 0.2s, background 0.2s",
                        gap: 8, minWidth: 0,
                      }}>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#e8e8e8", display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                            {isActive ? <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#1affd5", display: "inline-block", flexShrink: 0 }} /> : null}
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{tpl.name}</span>
                            {builtinBadge}
                          </div>
                          {tpl.description ? <div className="muted-small" style={{ fontSize: 11, marginTop: 2 }}>{tpl.description}</div> : null}
                        </div>
                        <div style={{ display: "flex", gap: 5, flexShrink: 0 }}>
                          <button onClick={() => loadTemplate(tpl)}
                            style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #1affd5", background: "transparent", color: "#1affd5", cursor: "pointer" }}>
                            Load
                          </button>
                          {tpl.is_builtin !== 1 ? (
                            <button onClick={() => deleteTemplate(tpl.id)}
                              style={{ fontSize: 11, padding: "3px 8px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: "#ef4444", cursor: "pointer" }}>
                              🗑
                            </button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                  {templates.length === 0 ? <div className="muted-small" style={{ fontSize: 11 }}>No templates yet.</div> : null}
                </div>
              </div>

              {/* Save current canvas as template */}
              <div style={{ borderTop: "1px solid #2d3348", paddingTop: 12 }}>
                <div className="muted-small" style={{ marginBottom: 6, fontSize: 11 }}>Save canvas as template</div>
                <input placeholder="Workflow name" value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  style={{ marginBottom: 6 }} />
                <input placeholder="Description (optional)" value={templateDesc}
                  onChange={(e) => setTemplateDesc(e.target.value)}
                  style={{ marginBottom: 8 }} />
                <button onClick={saveTemplate} disabled={savingTemplate} className="primary-btn" style={{ width: "100%", fontSize: 12 }}>
                  {savingTemplate ? "Saving..." : "Save as template"}
                </button>
                {templateMsg ? <div style={{ fontSize: 11, marginTop: 6, color: templateMsg.startsWith("✓") ? "#22c55e" : "#f59e0b" }}>{templateMsg}</div> : null}
              </div>
            </div>
          </div>
        </section>

        {/* ── Bottom Panel ── */}
        <section className="bottom-panel">
          <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #2d3348", paddingInline: 16, paddingTop: 12 }}>
            <button style={tabStyle("runs")} onClick={() => setBottomTab("runs")}>Run History</button>
            <button style={tabStyle("messages")} onClick={() => setBottomTab("messages")}>
              Messages {selectedRun ? `— Run #${selectedRun.id}` : ""}
            </button>
            <button style={tabStyle("monitor")} onClick={() => setBottomTab("monitor")}>Live Monitor</button>
            <button style={tabStyle("scheduled")} onClick={() => setBottomTab("scheduled")}>Scheduled Jobs</button>
          </div>

          <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
            {bottomTab === "runs" && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div className="eyebrow">History</div>
                  <button onClick={loadRuns}
                    style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #2d3348", background: "transparent", color: "#6b7280", cursor: "pointer" }}>
                    ↻ Refresh
                  </button>
                </div>
                <div className="list">
                  {runs.map((run) => (
                    <div key={run.id} className="list-item" style={{ cursor: "pointer", flexDirection: "column", alignItems: "flex-start", gap: 4 }}
                      onClick={() => loadMessages(run.id)}>
                      <div style={{ display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center" }}>
                        <strong style={{ fontSize: 13 }}>Run #{run.id}</strong>
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                          background: run.status === "completed" ? "#22c55e20" : run.status === "failed" ? "#ef444420" : "#f59e0b20",
                          color: run.status === "completed" ? "#22c55e" : run.status === "failed" ? "#ef4444" : "#f59e0b",
                        }}>{run.status}</span>
                      </div>
                      <div className="muted-small" style={{ fontSize: 11 }}>{run.user_input?.slice(0, 80)}{run.user_input?.length > 80 ? "..." : ""}</div>
                      <div style={{ display: "flex", gap: 12, fontSize: 10, color: "#6b7280" }}>
                        {run.total_tokens ? <span>🔢 {run.total_tokens} tokens</span> : null}
                        {run.total_cost_usd ? <span>💰 ${run.total_cost_usd.toFixed(4)}</span> : null}
                        {run.created_at ? <span>🕐 {new Date(run.created_at).toLocaleTimeString()}</span> : null}
                      </div>
                    </div>
                  ))}
                  {runs.length === 0 ? <div className="muted-small">No runs yet. Run a workflow above.</div> : null}
                </div>
              </div>
            )}

            {bottomTab === "messages" && (
              <div>
                <div className="eyebrow" style={{ marginBottom: 10 }}>
                  {selectedRun ? `Messages — Run #${selectedRun.id} (${selectedRun.status})` : "Select a run to view messages"}
                </div>
                <div className="list">
                  {messages.map((msg) => (
                    <div key={msg.id} className="list-item" style={{ flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <MessageTypeTag type={msg.message_type} />
                        {msg.agent_name ? <span style={{ fontSize: 11, color: "#6b7280" }}>{msg.agent_name}</span> : null}
                      </div>
                      <div style={{ fontSize: 12, color: "#d1d5db", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{msg.content}</div>
                    </div>
                  ))}
                  {messages.length === 0 ? <div className="muted-small">No messages. Click a run above.</div> : null}
                </div>
              </div>
            )}

            {bottomTab === "monitor" && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div className="eyebrow">Live Events (WebSocket)</div>
                  <button onClick={() => setLiveEvents([])}
                    style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #2d3348", background: "transparent", color: "#6b7280", cursor: "pointer" }}>
                    Clear
                  </button>
                </div>
                <div className="list">
                  {liveEvents.map((evt, i) => (
                    <div key={i} className="list-item" style={{ flexDirection: "column", alignItems: "flex-start", gap: 3 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <MessageTypeTag type={evt.type || "log"} />
                        {evt.agent ? <span style={{ fontSize: 11, color: "#6b7280" }}>{evt.agent}</span> : null}
                        {evt.run_id ? <span style={{ fontSize: 10, color: "#4b5563" }}>run #{evt.run_id}</span> : null}
                      </div>
                      <div style={{ fontSize: 12, color: "#d1d5db", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{evt.content || JSON.stringify(evt)}</div>
                    </div>
                  ))}
                  {liveEvents.length === 0 ? <div className="muted-small">Waiting for live events… Run a workflow to see activity.</div> : null}
                </div>
              </div>
            )}

            {bottomTab === "scheduled" && <ScheduledJobsPanel />}
          </div>
        </section>
      </main>
    </div>
  );
}
