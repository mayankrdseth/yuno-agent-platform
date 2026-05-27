import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import ReactFlow, { Background, Controls } from "reactflow";

const API_BASE = "http://127.0.0.1:8000";

const initialNodes = [
  {
    id: "1",
    position: { x: 80, y: 80 },
    data: { label: "Orchestrator" },
    type: "default",
  },
  {
    id: "2",
    position: { x: 320, y: 80 },
    data: { label: "Research Agent" },
    type: "default",
  },
  {
    id: "3",
    position: { x: 560, y: 80 },
    data: { label: "Writer Agent" },
    type: "default",
  },
];

const initialEdges = [
  { id: "e1-2", source: "1", target: "2", animated: true },
  { id: "e2-3", source: "2", target: "3", animated: true },
];

function App() {
  const [agents, setAgents] = useState([]);
  const [runs, setRuns] = useState([]);
  const [messages, setMessages] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [loading, setLoading] = useState(false);

  const [agentForm, setAgentForm] = useState({
    name: "",
    role: "",
    system_prompt: "",
    model: "llama-3.3-70b-versatile",
    tools: "web_search",
    channels: "telegram",
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
    setAgents(res.data);
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
      tools: agentForm.tools
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      channels: agentForm.channels
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      schedule: agentForm.schedule || null,
    };

    await axios.post(`${API_BASE}/agents`, payload);
    setAgentForm({
      name: "",
      role: "",
      system_prompt: "",
      model: "llama-3.3-70b-versatile",
      tools: "web_search",
      channels: "telegram",
      is_active: true,
      max_iterations: 5,
      memory_enabled: true,
      schedule: "",
    });
    await loadAgents();
  }

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
      setLiveEvents((prev) => [data, ...prev].slice(0, 20));
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
              placeholder="Role"
              value={agentForm.role}
              onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value })}
              required
            />
            <textarea
              placeholder="System prompt"
              rows="5"
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
            <input
              placeholder="Tools (comma-separated)"
              value={agentForm.tools}
              onChange={(e) => setAgentForm({ ...agentForm, tools: e.target.value })}
            />
            <input
              placeholder="Channels (comma-separated)"
              value={agentForm.channels}
              onChange={(e) =>
                setAgentForm({ ...agentForm, channels: e.target.value })
              }
            />
            <input
              type="number"
              min="1"
              max="20"
              placeholder="Max iterations"
              value={agentForm.max_iterations}
              onChange={(e) =>
                setAgentForm({
                  ...agentForm,
                  max_iterations: Number(e.target.value),
                })
              }
            />
            <button className="primary-btn" type="submit">
              Create agent
            </button>
          </form>
        </section>

        <section className="panel">
          <h2>Agents</h2>
          <div className="list">
            {agents.map((agent) => (
              <div className="list-item" key={agent.id}>
                <div>
                  <strong>{agent.name}</strong>
                  <div className="muted-small">{agent.role}</div>
                </div>
                <span className="badge">{agent.model}</span>
              </div>
            ))}
            {agents.length === 0 && <div className="muted-small">No agents yet.</div>}
          </div>
        </section>
      </aside>

      <main className="main-content">
        <section className="top-grid">
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="eyebrow">Workflow</div>
                <h2>Visual Builder</h2>
              </div>
            </div>
            <div className="flow-wrap">
              <ReactFlow nodes={initialNodes} edges={initialEdges} fitView>
                <Background />
                <Controls />
              </ReactFlow>
            </div>
          </div>

          <div className="panel">
            <div className="eyebrow">Execution</div>
            <h2>Run Demo Workflow</h2>
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
                <div className="message-card" key={msg.id}>
                  <div className="message-meta">
                    <strong>{msg.sender}</strong>
                    <span className="muted-small">
                      {msg.receiver ? `→ ${msg.receiver}` : ""}
                    </span>
                    <span className="badge subtle">{msg.message_type}</span>
                  </div>
                  <div>{msg.content}</div>
                </div>
              ))}
              {selectedRunId && messages.length === 0 && (
                <div className="muted-small">No messages found.</div>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="eyebrow">Monitoring</div>
                <h2>Live Event Stream</h2>
              </div>
            </div>
            <div className="messages">
              {liveEvents.map((event, idx) => (
                <div className="message-card" key={idx}>
                  <div className="message-meta">
                    <strong>{event.sender}</strong>
                    <span className="muted-small">
                      {event.receiver ? `→ ${event.receiver}` : ""}
                    </span>
                    <span className="badge subtle">
                      run #{event.run_id} · {event.type}
                    </span>
                  </div>
                  <div>{event.content}</div>
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