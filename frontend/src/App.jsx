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

/* ───────────────────────────────────────────
   Custom Node — orchestrator gets amber ring, agent is default
─────────────────────────────────────────── */
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
      boxShadow: isOrchestrator
        ? "0 0 10px rgba(245,158,11,0.15)"
        : "0 4px 16px rgba(0,0,0,0.4)",
      cursor: "grab",
    }}>
      <Handle type="target" position={Position.Left}
        style={{ background: isOrchestrator ? "#f59e0b" : "#1affd5", width: 10, height: 10, border: "2px solid #0f1117" }} />

      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 2 }}>
        {isOrchestrator && (
          <span style={{
            fontSize: 9, background: "#f59e0b18", color: "#f59e0b",
            border: "1px solid #f59e0b35", borderRadius: 3,
            padding: "1px 5px", fontWeight: 700, letterSpacing: "0.04em",
          }}>ORCHESTRATOR</span>
        )}
      </div>

      <div style={{ fontWeight: 700, fontSize: 13, color: "#e8e8e8", marginBottom: 2 }}>{data.name}</div>
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

/* ───────────────────────────────────────────
   Helpers
─────────────────────────────────────────── */
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
      id: `e${a.id}-${agents[i + 1].id}`,
      source: String(a.id), target: String(agents[i + 1].id),
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
    id: `e${orch.id}-${a.id}`,
    source: String(orch.id), target: String(a.id),
    animated: true, style: { stroke: "#f59e0b80", strokeWidth: 1.5, strokeDasharray: "5 3" },
  }));

  return { nodes, edges };
}

function MessageTypeTag({ type }) {
  const colours = { input: "#0ea5e9", output: "#22c55e", log: "#6b7280", agent_message: "#8b5cf6", tool_call: "#f59e0b" };
  return (
    <span style={{ background: colours[type] || "#6b7280", color: "#fff", borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 600 }}>
      {type}
    </span>
  );
}

/* ───────────────────────────────────────────
   App
─────────────────────────────────────────── */
export default function App() {
  const [agents, setAgents] = useState([]);
  const [runs, setRuns] = useState([]);
  const [messages, setMessages] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runError, setRunError] = useState("");

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

  // ── Data loaders ──
  async function loadAgents() {
    const res = await axios.get(`${API_BASE}/agents`);
    const fetched = res.data;
    setAgents(fetched);
    // NOTE: Do NOT auto-populate canvas here — templates handle canvas state
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
    const res = await axios.get(`${API_BASE}/workflow-templates`);
    const data = res.data;
    setTemplates(data);
    if (!data.length) return;

    // Auto-load: prefer last selected (stored in sessionStorage), fallback to first
    const lastId = sessionStorage.getItem("lastTemplateId");
    const toLoad = (lastId && data.find((t) => String(t.id) === lastId)) ?? data[0];
    if (toLoad) await loadTemplate(toLoad, data);
  }

  // ── Agent CRUD ──
  async function createAgent(e) {
    e.preventDefault();
    const payload = {
      ...agentForm,
      schedule: agentForm.schedule || null,
      forbidden_topics: agentForm.forbidden_topics
        ? agentForm.forbidden_topics.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
      max_output_chars: agentForm.max_output_chars ? parseInt(agentForm.max_output_chars, 10) : null,
      // clear channels if not orchestrator
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

  // ── Workflow builder ──
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

  // ── Templates ──
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

  // agentOverride lets loadTemplates() pass already-fetched agents to avoid a race condition
  async function loadTemplate(tpl, agentOverride) {
    const currentAgents = agentOverride ?? (agents.length ? agents : await loadAgents());
    let resolvedIds;
    if (tpl.is_builtin) {
      const nameToId = Object.fromEntries(currentAgents.map((a) => [a.name.toLowerCase(), a.id]));
      resolvedIds = tpl.agent_ids
        .map((nameOrId) => typeof nameOrId === "number" ? nameOrId : nameToId[String(nameOrId).toLowerCase()] ?? null)
        .filter(Boolean);
    } else {
      resolvedIds = tpl.agent_ids;
    }
    if (!resolvedIds.length) { alert("No matching agents found for this template. Create the agents first."); return; }
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
    // Remember this selection for next page load
    setActiveTemplateId(tpl.id);
    sessionStorage.setItem("lastTemplateId", String(tpl.id));
  }

  async function deleteTemplate(id) {
    if (!window.confirm("Delete this workflow template?")) return;
    try {
      await axios.delete(`${API_BASE}/workflow-templates/${id}`);
      if (activeTemplateId === id) {
        setActiveTemplateId(null);
        sessionStorage.removeItem("lastTemplateId");
        setNodes([]); setEdges([]);
      }
      await loadTemplates();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to delete template.");
    }
  }

  // ── Run workflow ──
  async function runWorkflow() {
    setRunError("");
    const hasOrch = nodes.some((n) => n.data.role === "orchestrator");
    if (!hasOrch) {
      setRunError("Add an Orchestrator agent to the canvas before running.");
      return;
    }
    if (nodes.length < 2) {
      setRunError("Add at least 2 agents (1 orchestrator + 1 specialist) to the canvas.");
      return;
    }
    setLoading(true);
    try {
      const agent_ids = nodes.map((n) => parseInt(n.id, 10));
      const edgePayload = edges.map((e) => ({ source: e.source, target: e.target }));
      await axios.post(`${API_BASE}/workflows/demo-run`, {
        user_input: workflowInput, agent_ids, edges: edgePayload,
      });
      await loadRuns();
    } catch (err) {
      setRunError(err?.response?.data?.detail || "Workflow run failed. Check backend logs.");
    } finally { setLoading(false); }
  }

  useEffect(() => { loadAgents(); loadRuns(); loadTemplates(); }, []);

  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws/monitor");
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      setLiveEvents((prev) => [data, ...prev].slice(0, 30));
    };
    return () => ws.close();
  }, []);

  const selectedRun = useMemo(() => runs.find((r) => r.id === selectedRunId), [runs, selectedRunId]);

  return (
    <div className="app-shell">
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

            {/* Role dropdown — only two values */}
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

            {/* Model */}
            <div>
              <div className="muted-small" style={{ marginBottom: 4 }}>Model</div>
              <select value={agentForm.model}
                onChange={(e) => setAgentForm({ ...agentForm, model: e.target.value })}
                style={{ width: "100%", background: "#0f1117", color: "#e8e8e8", border: "1px solid #2d3348", borderRadius: 6, padding: "7px 10px", fontSize: 13 }}>
                {AVAILABLE_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>

            {/* Tools */}
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

            {/* Channels — only visible for orchestrator */}
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

            {/* Guardrails */}
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
                  <div style={{ display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                        <strong>{agent.name}</strong>
                        {isOrch && (
                          <span style={{ fontSize: 9, background: "#f59e0b18", color: "#f59e0b", border: "1px solid #f59e0b35", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>ORCH</span>
                        )}
                      </div>
                      <div className="muted-small">{agent.role}</div>
                    </div>
                    <div style={{ display: "flex", gap: 5 }}>
                      {!inGraph ? (
                        <button onClick={() => addAgentToWorkflow(agent)}
                          style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #1affd5", background: "transparent", color: "#1affd5", cursor: "pointer" }}>
                          + Add
                        </button>
                      ) : (
                        <button onClick={() => removeAgentFromWorkflow(agent.id)}
                          style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #f87171", background: "transparent", color: "#f87171", cursor: "pointer" }}>
                          − Remove
                        </button>
                      )}
                      <button onClick={() => deleteAgent(agent.id)} title="Delete from database"
                        style={{ fontSize: 13, padding: "3px 8px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: "#ef4444", cursor: "pointer" }}>
                        🗑
                      </button>
                    </div>
                  </div>
                  {tools.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {tools.map((t) => <span key={t} className="badge" style={{ background: "#f59e0b20", color: "#f59e0b", fontSize: 10 }}>🔧 {t}</span>)}
                    </div>
                  )}
                  {channels.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {channels.map((c) => <span key={c} className="badge" style={{ background: "#0ea5e920", color: "#0ea5e9", fontSize: 10 }}>📡 {c}</span>)}
                    </div>
                  )}
                </div>
              );
            })}
            {agents.length === 0 && <div className="muted-small">No agents yet.</div>}
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
                {!nodes.some((n) => n.data.role === "orchestrator") && nodes.length > 0 && (
                  <span style={{ color: "#f59e0b", marginLeft: 6 }}>⚠ No orchestrator on canvas.</span>
                )}
              </div>
              <textarea rows="4" value={workflowInput} onChange={(e) => setWorkflowInput(e.target.value)} />
              {runError && (
                <div style={{ color: "#f87171", fontSize: 12, marginTop: 6, padding: "6px 10px", background: "#f8717115", borderRadius: 6, border: "1px solid #f8717130" }}>
                  ⚠ {runError}
                </div>
              )}
              <button className="primary-btn" onClick={runWorkflow} disabled={loading}>
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
                    return (
                      <div key={tpl.id} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        background: isActive ? "#1affd508" : "#0f1117",
                        borderRadius: 6, padding: "7px 10px",
                        border: isActive ? "1px solid #1affd540" : "1px solid #2d3348",
                        transition: "border-color 0.2s, background 0.2s",
                      }}>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#e8e8e8", display: "flex", alignItems: "center", gap: 6 }}>
                            {isActive && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#1affd5", display: "inline-block", flexShrink: 0 }} />}
                            {tpl.name}
                            {tpl.is_builtin === 1 && <span style={{ fontSize: 9, background: "#1affd520", color: "#1affd5", border: "1px solid #1affd540", borderRadius: 3, padding: "1px 5px" }}>BUILT-IN</span>}
                          </div>
                          {tpl.description && <div style={{ fontSize: 10, color: "#6b7280", marginTop: 2 }}>{tpl.description}</div>}
                        </div>
                        <div style={{ display: "flex", gap: 5 }}>
                          <button onClick={() => loadTemplate(tpl)}
                            style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #1affd5", background: "transparent", color: "#1affd5", cursor: "pointer" }}>
                            Load
                          </button>
                          {tpl.is_builtin !== 1 && (
                            <button onClick={() => deleteTemplate(tpl.id)}
                              style={{ fontSize: 11, padding: "3px 7px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: "#ef4444", cursor: "pointer" }}>
                              🗑
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {templates.length === 0 && <div className="muted-small" style={{ fontSize: 11 }}>No templates yet.</div>}
                </div>
              </div>
              <div style={{ borderTop: "1px solid #2d3348", paddingTop: 10 }}>
                <div className="muted-small" style={{ marginBottom: 6, fontSize: 11 }}>Save current canvas as template</div>
                <input placeholder="Workflow name" value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)} style={{ width: "100%", marginBottom: 6 }} />
                <input placeholder="Description (optional)" value={templateDesc}
                  onChange={(e) => setTemplateDesc(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
                {templateMsg && (
                  <div style={{ fontSize: 11, marginBottom: 6, color: templateMsg.startsWith("✓") ? "#22c55e" : "#f87171" }}>{templateMsg}</div>
                )}
                <button className="primary-btn" onClick={saveTemplate} disabled={savingTemplate} style={{ fontSize: 12, padding: "7px 14px" }}>
                  {savingTemplate ? "Saving..." : "Save as template"}
                </button>
              </div>
            </div>
          </div>
        </section>

        <section className="content-grid">

          {/* ── Workflow Runs ── */}
          <div className="panel">
            <div className="panel-header">
              <div><div className="eyebrow">Persistence</div><h2>Workflow Runs</h2></div>
            </div>
            <div className="list">
              {runs.map((run) => (
                <button key={run.id} className={`run-card ${selectedRunId === run.id ? "active" : ""}`} onClick={() => loadMessages(run.id)}>
                  <div className="run-card-top"><strong>Run #{run.id}</strong><span className="badge">{run.status}</span></div>
                  <div className="muted-small">{run.workflow_name}</div>
                  <div className="run-input">{run.input_text}</div>
                  {run.total_tokens != null && (
                    <div style={{ fontSize: 10, color: "#6b7280", marginTop: 3 }}>
                      🪙 {run.total_tokens} tokens{run.estimated_cost_usd != null ? ` · $${run.estimated_cost_usd.toFixed(5)}` : ""}
                    </div>
                  )}
                </button>
              ))}
              {runs.length === 0 && <div className="muted-small">No runs yet.</div>}
            </div>
          </div>

          {/* ── Message History ── */}
          <div className="panel">
            <div className="panel-header">
              <div><div className="eyebrow">Messages</div>
                <h2>{selectedRun ? `Run #${selectedRun.id} History` : "Select a run"}</h2>
              </div>
            </div>
            <div className="messages">
              {messages.map((msg) => (
                <div className="message-card" key={msg.id} style={msg.message_type === "tool_call" ? { borderLeft: "3px solid #f59e0b" } : {}}>
                  <div className="message-meta">
                    <strong>{msg.sender}</strong>
                    <span className="muted-small">{msg.receiver ? `→ ${msg.receiver}` : ""}</span>
                    <MessageTypeTag type={msg.message_type} />
                  </div>
                  <div style={{ fontSize: 13 }}>{msg.content}</div>
                </div>
              ))}
              {selectedRunId && messages.length === 0 && <div className="muted-small">No messages found.</div>}
            </div>
          </div>

          {/* ── Live Monitor ── */}
          <div className="panel">
            <div className="panel-header">
              <div><div className="eyebrow">Monitoring</div><h2>Live Event Stream</h2></div>
            </div>
            <div className="messages">
              {liveEvents.map((event, idx) => (
                <div className="message-card" key={idx} style={event.type === "tool_call" ? { borderLeft: "3px solid #f59e0b" } : {}}>
                  <div className="message-meta">
                    <strong>{event.sender}</strong>
                    <span className="muted-small">{event.receiver ? `→ ${event.receiver}` : ""}</span>
                    <span className="badge subtle">run #{event.run_id} · {event.type}</span>
                  </div>
                  <div style={{ fontSize: 13 }}>{event.content}</div>
                </div>
              ))}
              {liveEvents.length === 0 && <div className="muted-small">Waiting for events...</div>}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
