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

/* ─────────────────────────────────────────
   Custom Node
───────────────────────────────────────── */
function CustomAgentNode({ data }) {
  const tools = data.tools || [];
  const channels = data.channels || [];
  const visibleTools = tools.slice(0, 3);
  const extraTools = tools.length - visibleTools.length;

  return (
    <div style={{
      background: "#1a1f2e",
      border: data.pending ? "2px dashed #1affd5" : "1px solid #2d3348",
      borderRadius: 10, padding: "10px 14px",
      minWidth: 180, maxWidth: 220,
      boxShadow: "0 4px 16px rgba(0,0,0,0.4)", cursor: "grab",
    }}>
      <Handle type="target" position={Position.Left}
        style={{ background: "#1affd5", width: 10, height: 10, border: "2px solid #0f1117" }} />

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
        style={{ background: "#1affd5", width: 10, height: 10, border: "2px solid #0f1117" }} />
    </div>
  );
}

const nodeTypes = { agentNode: CustomAgentNode };

/* ─────────────────────────────────────────
   Helpers
───────────────────────────────────────── */
function parseList(val) {
  if (Array.isArray(val)) return val;
  try { return JSON.parse(val || "[]"); } catch { return []; }
}

function buildAgentNode(agent, index, total) {
  const cols = Math.min(total, 4);
  return {
    id: String(agent.id),
    type: "agentNode",
    position: { x: 80 + (index % cols) * 280, y: 60 + Math.floor(index / cols) * 220 },
    data: { name: agent.name, role: agent.role, tools: parseList(agent.tools), channels: parseList(agent.channels), pending: false },
  };
}

function buildEdgesFromAgents(agents) {
  return agents.slice(0, -1).map((agent, i) => ({
    id: `e${agent.id}-${agents[i + 1].id}`,
    source: String(agent.id), target: String(agents[i + 1].id),
    animated: true, style: { stroke: "#1affd5", strokeWidth: 2 },
  }));
}

function MessageTypeTag({ type }) {
  const colours = { input: "#0ea5e9", output: "#22c55e", log: "#6b7280", agent_message: "#8b5cf6", tool_call: "#f59e0b" };
  return (
    <span style={{ background: colours[type] || "#6b7280", color: "#fff", borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 600 }}>
      {type}
    </span>
  );
}

/* ─────────────────────────────────────────
   App
───────────────────────────────────────── */
export default function App() {
  const [agents, setAgents] = useState([]);
  const [runs, setRuns] = useState([]);
  const [messages, setMessages] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runError, setRunError] = useState("");

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const [agentForm, setAgentForm] = useState({
    name: "", role: "", system_prompt: "",
    model: "llama-3.3-70b-versatile",
    tools: [], channels: [],
    is_active: true, max_iterations: 5,
    memory_enabled: true, schedule: "",
  });

  const [workflowInput, setWorkflowInput] = useState(
    "Research the benefits of agent orchestration platforms for enterprise support."
  );

  // ── Data loaders ──
  async function loadAgents() {
    const res = await axios.get(`${API_BASE}/agents`);
    const fetched = res.data;
    setAgents(fetched);
    setNodes(fetched.map((a, i) => buildAgentNode(a, i, fetched.length)));
    setEdges(buildEdgesFromAgents(fetched));
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

  // ── Agent CRUD ──
  async function createAgent(e) {
    e.preventDefault();
    await axios.post(`${API_BASE}/agents`, { ...agentForm, schedule: agentForm.schedule || null });
    setAgentForm({ name: "", role: "", system_prompt: "", model: "llama-3.3-70b-versatile", tools: [], channels: [], is_active: true, max_iterations: 5, memory_enabled: true, schedule: "" });
    await loadAgents();
  }

  async function deleteAgent(agentId) {
    if (!window.confirm("Delete this agent from the database permanently?")) return;
    await axios.delete(`${API_BASE}/agents/${agentId}`);
    // Also remove from canvas if present
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
    const lastNode = nodes[nodes.length - 1];
    setNodes((nds) => [...nds, {
      id: String(agent.id), type: "agentNode",
      position: { x: lastNode ? lastNode.position.x + 300 : 80, y: lastNode ? lastNode.position.y + 60 : 100 },
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

  // ── Run workflow (Model B: send canvas state) ──
  async function runWorkflow() {
    setRunError("");

    // Guard: need at least 2 agents on canvas
    if (nodes.length < 2) {
      setRunError("Add at least 2 agents to the workflow canvas before running.");
      return;
    }

    setLoading(true);
    try {
      // Extract integer IDs from canvas nodes (node.id is a string like "3")
      const agent_ids = nodes.map((n) => parseInt(n.id, 10));
      // Send edges so backend knows the connection topology
      const edgePayload = edges.map((e) => ({ source: e.source, target: e.target }));

      await axios.post(`${API_BASE}/workflows/demo-run`, {
        user_input: workflowInput,
        agent_ids,
        edges: edgePayload,
      });
      await loadRuns();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setRunError(detail || "Workflow run failed. Check backend logs.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadAgents(); loadRuns(); }, []);

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
            <input placeholder="Agent name" value={agentForm.name} onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })} required />
            <input placeholder="Role (e.g. Orchestrator, Research Specialist)" value={agentForm.role} onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value })} required />
            <textarea placeholder="System prompt" rows="4" value={agentForm.system_prompt} onChange={(e) => setAgentForm({ ...agentForm, system_prompt: e.target.value })} required />
            <input placeholder="Model" value={agentForm.model} onChange={(e) => setAgentForm({ ...agentForm, model: e.target.value })} />

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

            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Channels</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {AVAILABLE_CHANNELS.map((ch) => (
                  <label key={ch} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={agentForm.channels.includes(ch)} onChange={() => toggleChannel(ch)} />
                    {ch}
                  </label>
                ))}
              </div>
            </div>

            <input type="number" min="1" max="20" placeholder="Max iterations" value={agentForm.max_iterations}
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
              return (
                <div className="list-item" key={agent.id} style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
                  <div style={{ display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <strong>{agent.name}</strong>
                      <div className="muted-small">{agent.role}</div>
                    </div>
                    <div style={{ display: "flex", gap: 5 }}>
                      {/* Canvas toggle */}
                      {!inGraph ? (
                        <button onClick={() => addAgentToWorkflow(agent)} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #1affd5", background: "transparent", color: "#1affd5", cursor: "pointer" }}>
                          + Add
                        </button>
                      ) : (
                        <button onClick={() => removeAgentFromWorkflow(agent.id)} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "1px solid #f87171", background: "transparent", color: "#f87171", cursor: "pointer" }}>
                          − Remove
                        </button>
                      )}
                      {/* Delete from DB */}
                      <button
                        onClick={() => deleteAgent(agent.id)}
                        title="Delete from database"
                        style={{ fontSize: 13, padding: "3px 8px", borderRadius: 4, border: "1px solid #ef444430", background: "transparent", color: "#ef4444", cursor: "pointer" }}
                      >
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
                Drag handles to connect &nbsp;·&nbsp; Select + Delete removes edge/node &nbsp;·&nbsp; Only canvas agents run
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
                <MiniMap nodeColor={() => "#1a1f2e"} maskColor="rgba(10,12,20,0.7)"
                  style={{ background: "#0f1117", border: "1px solid #2d3348" }} />
              </ReactFlow>
            </div>
          </div>

          {/* ── Run Workflow ── */}
          <div className="panel">
            <div className="eyebrow">Execution</div>
            <h2>Run Workflow</h2>
            <div className="muted-small" style={{ marginBottom: 8, fontSize: 11 }}>
              Runs only the {nodes.length} agent{nodes.length !== 1 ? "s" : ""} currently on the canvas.
            </div>
            <textarea rows="6" value={workflowInput} onChange={(e) => setWorkflowInput(e.target.value)} />
            {runError && (
              <div style={{ color: "#f87171", fontSize: 12, marginTop: 6, padding: "6px 10px", background: "#f8717115", borderRadius: 6, border: "1px solid #f8717130" }}>
                ⚠ {runError}
              </div>
            )}
            <button className="primary-btn" onClick={runWorkflow} disabled={loading}>
              {loading ? "Running..." : `Run workflow (${nodes.length} agents)`}
            </button>
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
