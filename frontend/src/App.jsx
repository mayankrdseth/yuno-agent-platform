import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import ReactFlow, {
  Background,
  Controls,
  addEdge,
  useEdgesState,
  useNodesState,
} from "reactflow";
import "reactflow/dist/style.css";

const API_BASE = "http://127.0.0.1:8000";

const AVAILABLE_TOOLS = ["web_search", "wikipedia", "calculator", "datetime"];
const AVAILABLE_CHANNELS = ["telegram", "slack", "whatsapp"];

// Build nodes from agents array
function buildNodesFromAgents(agents) {
  if (agents.length === 0) return [];
  const spacing = 260;
  return agents.map((agent, i) => ({
    id: String(agent.id),
    position: { x: 80 + i * spacing, y: 100 },
    data: {
      label: (
        <div style={{ textAlign: "center", fontSize: 13 }}>
          <div style={{ fontWeight: 700 }}>{agent.name}</div>
          <div style={{ fontSize: 11, opacity: 0.6, marginTop: 2 }}>{agent.role}</div>
        </div>
      ),
    },
    type: "default",
  }));
}

function buildEdgesFromAgents(agents) {
  const edges = [];
  for (let i = 0; i < agents.length - 1; i++) {
    edges.push({
      id: `e${agents[i].id}-${agents[i + 1].id}`,
      source: String(agents[i].id),
      target: String(agents[i + 1].id),
      animated: true,
    });
  }
  return edges;
}

function MessageTypeTag({ type }) {
  const colours = {
    input: "#0ea5e9",
    output: "#22c55e",
    log: "#6b7280",
    agent_message: "#8b5cf6",
    tool_call: "#f59e0b",
  };
  return (
    <span
      style={{
        background: colours[type] || "#6b7280",
        color: "#fff",
        borderRadius: 4,
        padding: "1px 7px",
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      {type}
    </span>
  );
}

function App() {
  const [agents, setAgents] = useState([]);
  const [runs, setRuns] = useState([]);
  const [messages, setMessages] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [loading, setLoading] = useState(false);

  // Workflow builder state
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const [agentForm, setAgentForm] = useState({
    name: "",
    role: "",
    system_prompt: "",
    model: "llama-3.3-70b-versatile",
    tools: [],
    channels: [],
    is_active: true,
    max_iterations: 5,
    memory_enabled: true,
    schedule: "",
  });

  const [workflowInput, setWorkflowInput] = useState(
    "Research the benefits of agent orchestration platforms for enterprise support."
  );

  async function loadAgents() {
    const res = await axios.get(`${API_BASE}/agents`);
    const fetched = res.data;
    setAgents(fetched);
    // Sync workflow builder with DB agents
    setNodes(buildNodesFromAgents(fetched));
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

  async function createAgent(e) {
    e.preventDefault();
    const payload = {
      ...agentForm,
      schedule: agentForm.schedule || null,
    };
    await axios.post(`${API_BASE}/agents`, payload);
    setAgentForm({
      name: "",
      role: "",
      system_prompt: "",
      model: "llama-3.3-70b-versatile",
      tools: [],
      channels: [],
      is_active: true,
      max_iterations: 5,
      memory_enabled: true,
      schedule: "",
    });
    await loadAgents();
  }

  function toggleTool(tool) {
    setAgentForm((f) => ({
      ...f,
      tools: f.tools.includes(tool)
        ? f.tools.filter((t) => t !== tool)
        : [...f.tools, tool],
    }));
  }

  function toggleChannel(ch) {
    setAgentForm((f) => ({
      ...f,
      channels: f.channels.includes(ch)
        ? f.channels.filter((c) => c !== ch)
        : [...f.channels, ch],
    }));
  }

  function addAgentToWorkflow(agent) {
    const alreadyInGraph = nodes.find((n) => n.id === String(agent.id));
    if (alreadyInGraph) return;
    const newNode = {
      id: String(agent.id),
      position: { x: 80 + nodes.length * 260, y: 100 },
      data: {
        label: (
          <div style={{ textAlign: "center", fontSize: 13 }}>
            <div style={{ fontWeight: 700 }}>{agent.name}</div>
            <div style={{ fontSize: 11, opacity: 0.6, marginTop: 2 }}>{agent.role}</div>
          </div>
        ),
      },
      type: "default",
    };
    setNodes((nds) => [...nds, newNode]);
    // Auto-connect to last node
    if (nodes.length > 0) {
      const lastNode = nodes[nodes.length - 1];
      setEdges((eds) =>
        addEdge(
          { id: `e${lastNode.id}-${agent.id}`, source: lastNode.id, target: String(agent.id), animated: true },
          eds
        )
      );
    }
  }

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge({ ...params, animated: true }, eds)),
    [setEdges]
  );

  async function runWorkflow() {
    setLoading(true);
    try {
      await axios.post(`${API_BASE}/workflows/demo-run`, {
        user_input: workflowInput,
      });
      await loadRuns();
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAgents();
    loadRuns();
  }, []);

  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws/monitor");
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setLiveEvents((prev) => [data, ...prev].slice(0, 30));
    };
    return () => ws.close();
  }, []);

  const selectedRun = useMemo(
    () => runs.find((r) => r.id === selectedRunId),
    [runs, selectedRunId]
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <div className="eyebrow">Yuno Challenge</div>
          <h1>Agent Orchestration Platform</h1>
          <p className="muted">
            Manage agents, run workflows, inspect history, and monitor live events.
          </p>
        </div>

        {/* ── Create Agent ── */}
        <section className="panel">
          <h2>Create Agent</h2>
          <form onSubmit={createAgent} className="form-grid">
            <input
              placeholder="Agent name"
              value={agentForm.name}
              onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })}
              required
            />
            <input
              placeholder="Role (e.g. Orchestrator, Research Specialist)"
              value={agentForm.role}
              onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value })}
              required
            />
            <textarea
              placeholder="System prompt"
              rows="4"
              value={agentForm.system_prompt}
              onChange={(e) =>
                setAgentForm({ ...agentForm, system_prompt: e.target.value })
              }
              required
            />
            <input
              placeholder="Model"
              value={agentForm.model}
              onChange={(e) => setAgentForm({ ...agentForm, model: e.target.value })}
            />

            {/* Tools checkboxes */}
            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Tools</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {AVAILABLE_TOOLS.map((tool) => (
                  <label key={tool} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={agentForm.tools.includes(tool)}
                      onChange={() => toggleTool(tool)}
                    />
                    {tool}
                  </label>
                ))}
              </div>
            </div>

            {/* Channels checkboxes */}
            <div>
              <div className="muted-small" style={{ marginBottom: 6 }}>Channels</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {AVAILABLE_CHANNELS.map((ch) => (
                  <label key={ch} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={agentForm.channels.includes(ch)}
                      onChange={() => toggleChannel(ch)}
                    />
                    {ch}
                  </label>
                ))}
              </div>
            </div>

            <input
              type="number"
              min="1"
              max="20"
              placeholder="Max iterations"
              value={agentForm.max_iterations}
              onChange={(e) =>
                setAgentForm({ ...agentForm, max_iterations: Number(e.target.value) })
              }
            />
            <button className="primary-btn" type="submit">Create agent</button>
          </form>
        </section>

        {/* ── Agent List ── */}
        <section className="panel">
          <h2>Agents</h2>
          <div className="list">
            {agents.map((agent) => {
              const tools = Array.isArray(agent.tools)
                ? agent.tools
                : JSON.parse(agent.tools || "[]");
              const channels = Array.isArray(agent.channels)
                ? agent.channels
                : JSON.parse(agent.channels || "[]");
              const inGraph = nodes.some((n) => n.id === String(agent.id));
              return (
                <div className="list-item" key={agent.id} style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
                  <div style={{ display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <strong>{agent.name}</strong>
                      <div className="muted-small">{agent.role}</div>
                    </div>
                    <button
                      onClick={() => addAgentToWorkflow(agent)}
                      style={{
                        fontSize: 11,
                        padding: "3px 10px",
                        borderRadius: 4,
                        border: "1px solid #1affd5",
                        background: inGraph ? "#1affd520" : "transparent",
                        color: "#1affd5",
                        cursor: inGraph ? "default" : "pointer",
                      }}
                      disabled={inGraph}
                    >
                      {inGraph ? "In workflow" : "+ Add to workflow"}
                    </button>
                  </div>
                  {tools.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {tools.map((t) => (
                        <span key={t} className="badge" style={{ background: "#f59e0b20", color: "#f59e0b", fontSize: 10 }}>{t}</span>
                      ))}
                    </div>
                  )}
                  {channels.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {channels.map((c) => (
                        <span key={c} className="badge" style={{ background: "#0ea5e920", color: "#0ea5e9", fontSize: 10 }}>{c}</span>
                      ))}
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
                Drag to connect nodes &middot; Agents auto-added from DB
              </div>
            </div>
            <div className="flow-wrap">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                fitView
              >
                <Background />
                <Controls />
              </ReactFlow>
            </div>
          </div>

          {/* ── Run Workflow ── */}
          <div className="panel">
            <div className="eyebrow">Execution</div>
            <h2>Run Workflow</h2>
            <textarea
              rows="6"
              value={workflowInput}
              onChange={(e) => setWorkflowInput(e.target.value)}
            />
            <button className="primary-btn" onClick={runWorkflow} disabled={loading}>
              {loading ? "Running..." : "Run workflow"}
            </button>
          </div>
        </section>

        <section className="content-grid">

          {/* ── Workflow Runs ── */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="eyebrow">Persistence</div>
                <h2>Workflow Runs</h2>
              </div>
            </div>
            <div className="list">
              {runs.map((run) => (
                <button
                  key={run.id}
                  className={`run-card ${selectedRunId === run.id ? "active" : ""}`}
                  onClick={() => loadMessages(run.id)}
                >
                  <div className="run-card-top">
                    <strong>Run #{run.id}</strong>
                    <span className="badge">{run.status}</span>
                  </div>
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
              <div>
                <div className="eyebrow">Messages</div>
                <h2>
                  {selectedRun ? `Run #${selectedRun.id} History` : "Select a run"}
                </h2>
              </div>
            </div>
            <div className="messages">
              {messages.map((msg) => (
                <div
                  className="message-card"
                  key={msg.id}
                  style={msg.message_type === "tool_call" ? { borderLeft: "3px solid #f59e0b" } : {}}
                >
                  <div className="message-meta">
                    <strong>{msg.sender}</strong>
                    <span className="muted-small">
                      {msg.receiver ? `→ ${msg.receiver}` : ""}
                    </span>
                    <MessageTypeTag type={msg.message_type} />
                  </div>
                  <div style={{ fontSize: 13 }}>{msg.content}</div>
                </div>
              ))}
              {selectedRunId && messages.length === 0 && (
                <div className="muted-small">No messages found.</div>
              )}
            </div>
          </div>

          {/* ── Live Monitor ── */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="eyebrow">Monitoring</div>
                <h2>Live Event Stream</h2>
              </div>
            </div>
            <div className="messages">
              {liveEvents.map((event, idx) => (
                <div
                  className="message-card"
                  key={idx}
                  style={event.type === "tool_call" ? { borderLeft: "3px solid #f59e0b" } : {}}
                >
                  <div className="message-meta">
                    <strong>{event.sender}</strong>
                    <span className="muted-small">
                      {event.receiver ? `→ ${event.receiver}` : ""}
                    </span>
                    <span className="badge subtle">run #{event.run_id} · {event.type}</span>
                  </div>
                  <div style={{ fontSize: 13 }}>{event.content}</div>
                </div>
              ))}
              {liveEvents.length === 0 && (
                <div className="muted-small">Waiting for events...</div>
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
