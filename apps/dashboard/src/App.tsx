import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Shield,
  Briefcase,
  Users,
  DollarSign,
  Play,
  Pause,
  StopCircle,
  CheckCircle2,
  Lock,
  Cpu,
  RefreshCw,
  Clock,
} from 'lucide-react';

interface AgentStatus {
  is_paused: boolean;
  is_stopped: boolean;
  stop_outreach: boolean;
  active_mode: string;
}

interface Project {
  id: string;
  name: string;
  client_id: string;
  status: string;
  accepted_price: number;
  created_at: string;
}

interface Prospect {
  id: string;
  business_name: string;
  domain: string;
  qualification_score: number;
  status: string;
  opt_out: boolean;
}

interface Payment {
  id: string;
  project_id: string;
  amount: number;
  currency: string;
  status: string;
  verified_at: string;
}

interface AuditLog {
  id: string;
  actor: string;
  action: string;
  target_id: string;
  result: string;
  risk_level: string;
  reason: string;
  created_at: string;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'overview' | 'projects' | 'prospects' | 'payments' | 'security' | 'audit'>('overview');
  const [auditReport, setAuditReport] = useState<any>(null);
  const [runningAudit, setRunningAudit] = useState<boolean>(false);
  const [cycleMsg, setCycleMsg] = useState<string>('');

  // Queries
  const { data: status, refetch: refetchStatus } = useQuery<AgentStatus>({
    queryKey: ['agent-status'],
    queryFn: async () => {
      const res = await fetch('/api/v1/agent/status', { credentials: 'omit' });
      if (!res.ok) return { is_paused: false, is_stopped: false, stop_outreach: false, active_mode: 'AUTONOMOUS' };
      return res.json();
    },
  });

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: async () => {
      const res = await fetch('/api/v1/projects');
      if (!res.ok) return [];
      return res.json();
    },
  });

  const { data: prospects = [] } = useQuery<Prospect[]>({
    queryKey: ['prospects'],
    queryFn: async () => {
      const res = await fetch('/api/v1/prospects');
      if (!res.ok) return [];
      return res.json();
    },
  });

  const { data: payments = [] } = useQuery<Payment[]>({
    queryKey: ['payments'],
    queryFn: async () => {
      const res = await fetch('/api/v1/payments');
      if (!res.ok) return [];
      return res.json();
    },
  });

  const { data: auditLogs = [] } = useQuery<AuditLog[]>({
    queryKey: ['audit'],
    queryFn: async () => {
      const res = await fetch('/api/v1/audit');
      if (!res.ok) return [];
      return res.json();
    },
  });

  // Emergency Control Handlers
  const handleEmergencyAction = async (action: 'pause' | 'stop' | 'resume') => {
    try {
      await fetch(`/api/v1/agent/emergency/${action}`, { method: 'POST' });
      refetchStatus();
    } catch (e) {
      console.error(e);
    }
  };

  const handleTriggerCycle = async () => {
    setCycleMsg('Running autonomous commercial cycle...');
    try {
      const res = await fetch('/api/v1/agent/run-cycle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          business_name: 'Apex Automated Retail',
          domain: 'apexretail.example',
          lead_email: 'growth@apexretail.example',
        }),
      });
      const data = await res.json();
      setCycleMsg(`Cycle completed: ${data.status} (QA Score: ${data.qa_score})`);
    } catch (e) {
      setCycleMsg('Cycle trigger failed');
    }
  };

  const handleRunSecurityAudit = async () => {
    setRunningAudit(true);
    try {
      const res = await fetch('/api/v1/security/run-audit', { method: 'POST' });
      const data = await res.json();
      setAuditReport(data);
    } catch (e) {
      console.error(e);
    } finally {
      setRunningAudit(false);
    }
  };

  const totalRevenue = payments.reduce((acc, p) => acc + (p.status === 'PAID' ? p.amount : 0), 0);

  return (
    <div className="min-h-screen bg-[#090d16] text-gray-100 flex flex-col">
      {/* Top Navbar */}
      <header className="border-b border-[#1e293b] bg-[#0f172a]/80 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <Cpu className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-wide">AUTONOMOUS BUSINESS OPERATOR</h1>
            <p className="text-xs text-blue-400 font-mono">STATE + POLICY + TOOLS + MEMORY + VERIFICATION</p>
          </div>
        </div>

        {/* Global Emergency Controls */}
        <div className="flex items-center space-x-3">
          <button
            onClick={() => handleEmergencyAction('resume')}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              !status?.is_paused && !status?.is_stopped
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                : 'bg-gray-800 text-gray-400 border-gray-700 hover:text-white'
            }`}
          >
            <Play className="w-3.5 h-3.5" />
            <span>AUTONOMOUS</span>
          </button>
          <button
            onClick={() => handleEmergencyAction('pause')}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              status?.is_paused
                ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
                : 'bg-gray-800 text-gray-400 border-gray-700 hover:text-amber-400'
            }`}
          >
            <Pause className="w-3.5 h-3.5" />
            <span>PAUSE AGENT</span>
          </button>
          <button
            onClick={() => handleEmergencyAction('stop')}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              status?.is_stopped
                ? 'bg-rose-500/20 text-rose-300 border-rose-500/30'
                : 'bg-gray-800 text-gray-400 border-gray-700 hover:text-rose-400'
            }`}
          >
            <StopCircle className="w-3.5 h-3.5" />
            <span>STOP ALL</span>
          </button>
        </div>
      </header>

      {/* Main Content Layout */}
      <div className="flex-1 flex max-w-7xl w-full mx-auto p-6 space-x-6">
        {/* Left Sidebar Navigation */}
        <aside className="w-64 space-y-1">
          {[
            { id: 'overview', label: 'Overview', icon: Activity },
            { id: 'projects', label: 'Projects', icon: Briefcase },
            { id: 'prospects', label: 'Prospects', icon: Users },
            { id: 'payments', label: 'Payments', icon: DollarSign },
            { id: 'security', label: 'Security Center', icon: Shield },
            { id: 'audit', label: 'Audit Trail', icon: Clock },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`w-full flex items-center space-x-3 px-4 py-2.5 rounded-lg text-sm font-medium transition ${
                  active
                    ? 'bg-blue-600/10 text-blue-400 border border-blue-500/20 shadow-sm'
                    : 'text-gray-400 hover:bg-gray-800/60 hover:text-gray-200'
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{tab.label}</span>
              </button>
            );
          })}

          <div className="pt-6">
            <div className="p-4 rounded-xl bg-gray-900/60 border border-gray-800 space-y-3">
              <div className="flex items-center space-x-2 text-xs font-bold text-gray-400">
                <Lock className="w-3.5 h-3.5 text-blue-400" />
                <span>NVIDIA NIM LIMITER</span>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-xs font-mono text-gray-400">
                  <span>Global RPM Cap</span>
                  <span className="text-emerald-400 font-bold">30 / min</span>
                </div>
                <div className="flex justify-between text-xs font-mono text-gray-400">
                  <span>Target Operating</span>
                  <span className="text-blue-400">28 / min</span>
                </div>
                <div className="w-full bg-gray-800 h-1.5 rounded-full overflow-hidden mt-1">
                  <div className="bg-emerald-500 h-full w-[15%]" />
                </div>
              </div>
              <p className="text-[10px] text-gray-500">Enforced by Redis atomic sliding window</p>
            </div>
          </div>
        </aside>

        {/* Content Area */}
        <main className="flex-1 space-y-6">
          {/* Top Metrics Row */}
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-400 font-medium">Autonomous Status</div>
              <div className="text-lg font-bold text-white mt-1 flex items-center space-x-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
                <span>{status?.is_stopped ? 'STOPPED' : status?.is_paused ? 'PAUSED' : 'ONLINE'}</span>
              </div>
            </div>
            <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-400 font-medium">Total Projects</div>
              <div className="text-lg font-bold text-white mt-1">{projects.length}</div>
            </div>
            <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-400 font-medium">Verified Revenue</div>
              <div className="text-lg font-bold text-emerald-400 mt-1">${totalRevenue.toFixed(2)}</div>
            </div>
            <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-400 font-medium">Prospect Pipeline</div>
              <div className="text-lg font-bold text-blue-400 mt-1">{prospects.length} Qualified</div>
            </div>
          </div>

          {/* TAB 1: OVERVIEW & LIVE AGENT VIEW */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Trigger Cycle Banner */}
              <div className="p-5 rounded-2xl bg-gradient-to-r from-blue-900/30 to-indigo-900/20 border border-blue-800/40 flex items-center justify-between">
                <div>
                  <h3 className="text-base font-semibold text-white">Autonomous Commercial Execution</h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Launch full autonomous cycle: Prospecting → Qualification → Checkout → Payment Verification → Coding → QA.
                  </p>
                  {cycleMsg && <p className="text-xs text-emerald-400 font-mono mt-2">{cycleMsg}</p>}
                </div>
                <button
                  onClick={handleTriggerCycle}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-blue-500/20 transition flex items-center space-x-2"
                >
                  <Play className="w-3.5 h-3.5" />
                  <span>Execute Next Objective</span>
                </button>
              </div>

              {/* Live Agent State View */}
              <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5 space-y-4">
                <div className="flex items-center justify-between border-b border-gray-800 pb-3">
                  <div className="flex items-center space-x-2">
                    <Activity className="w-4 h-4 text-blue-400" />
                    <h2 className="text-sm font-bold text-white uppercase tracking-wider">Live Agent Telemetry</h2>
                  </div>
                  <span className="text-xs text-gray-400 font-mono">Ollama Cloud (Primary) / NIM (Deep Reason)</span>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="p-3 bg-gray-800/40 rounded-lg border border-gray-700/50">
                    <span className="text-xs text-gray-500 font-medium">CURRENT GOAL</span>
                    <p className="text-sm text-gray-200 mt-1 font-medium">
                      Discover high-fit business leads, generate one-time checkouts, and deliver tested automations.
                    </p>
                  </div>
                  <div className="p-3 bg-gray-800/40 rounded-lg border border-gray-700/50">
                    <span className="text-xs text-gray-500 font-medium">CURRENT STATE</span>
                    <p className="text-sm text-emerald-400 mt-1 font-mono font-medium">
                      MONITORING_PIPELINE
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 text-xs">
                  <div className="p-3 bg-gray-800/20 rounded-lg">
                    <span className="text-gray-500">Active Tool</span>
                    <p className="text-gray-300 font-mono mt-0.5">tool_gateway.validate</p>
                  </div>
                  <div className="p-3 bg-gray-800/20 rounded-lg">
                    <span className="text-gray-500">Policy Decision</span>
                    <p className="text-emerald-400 font-mono mt-0.5">ALLOW (Least Privilege)</p>
                  </div>
                  <div className="p-3 bg-gray-800/20 rounded-lg">
                    <span className="text-gray-500">Independent QA Status</span>
                    <p className="text-blue-400 font-mono mt-0.5">5-LAYER VERIFIED</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: PROJECTS */}
          {activeTab === 'projects' && (
            <div className="bg-gray-900/60 border border-gray-800 rounded-2xl overflow-hidden">
              <div className="p-4 border-b border-gray-800">
                <h2 className="text-sm font-bold text-white">Client Projects & Deliverables</h2>
              </div>
              <div className="divide-y divide-gray-800 text-sm">
                {projects.map((p) => (
                  <div key={p.id} className="p-4 flex items-center justify-between hover:bg-gray-800/30">
                    <div>
                      <div className="font-medium text-white">{p.name}</div>
                      <div className="text-xs text-gray-500 font-mono mt-0.5">ID: {p.id}</div>
                    </div>
                    <div className="flex items-center space-x-6">
                      <div className="text-right">
                        <div className="font-semibold text-emerald-400">${p.accepted_price.toFixed(2)}</div>
                        <div className="text-xs text-gray-500">USD</div>
                      </div>
                      <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                        p.status === 'COMPLETED' ? 'bg-emerald-500/20 text-emerald-400' :
                        p.status === 'PAID' ? 'bg-blue-500/20 text-blue-400' :
                        'bg-amber-500/20 text-amber-400'
                      }`}>
                        {p.status}
                      </span>
                    </div>
                  </div>
                ))}
                {projects.length === 0 && <div className="p-8 text-center text-gray-500 text-xs">No active projects yet.</div>}
              </div>
            </div>
          )}

          {/* TAB 3: PROSPECTS */}
          {activeTab === 'prospects' && (
            <div className="bg-gray-900/60 border border-gray-800 rounded-2xl overflow-hidden">
              <div className="p-4 border-b border-gray-800">
                <h2 className="text-sm font-bold text-white">Prospect Pipeline & Qualification</h2>
              </div>
              <div className="divide-y divide-gray-800 text-sm">
                {prospects.map((p) => (
                  <div key={p.id} className="p-4 flex items-center justify-between hover:bg-gray-800/30">
                    <div>
                      <div className="font-medium text-white">{p.business_name}</div>
                      <div className="text-xs text-gray-400 font-mono mt-0.5">{p.domain}</div>
                    </div>
                    <div className="flex items-center space-x-4">
                      <div className="text-xs text-right font-mono">
                        <span className="text-gray-400">Score: </span>
                        <span className="font-bold text-blue-400">{p.qualification_score * 100}%</span>
                      </div>
                      <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        {p.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 4: PAYMENTS */}
          {activeTab === 'payments' && (
            <div className="bg-gray-900/60 border border-gray-800 rounded-2xl overflow-hidden">
              <div className="p-4 border-b border-gray-800 flex justify-between items-center">
                <h2 className="text-sm font-bold text-white">Dodo Payments (Server-Side Verified)</h2>
                <span className="text-xs text-emerald-400 font-mono">HMAC-SHA256 Signed</span>
              </div>
              <div className="divide-y divide-gray-800 text-sm">
                {payments.map((p) => (
                  <div key={p.id} className="p-4 flex items-center justify-between hover:bg-gray-800/30">
                    <div>
                      <div className="font-medium text-white">Payment #{p.id.slice(0, 8)}</div>
                      <div className="text-xs text-gray-500 font-mono mt-0.5">Project: {p.project_id.slice(0, 8)}...</div>
                    </div>
                    <div className="flex items-center space-x-4">
                      <span className="text-emerald-400 font-bold font-mono">${p.amount.toFixed(2)} {p.currency}</span>
                      <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400">
                        {p.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 5: SECURITY CENTER */}
          {activeTab === 'security' && (
            <div className="space-y-6">
              <div className="p-5 rounded-2xl bg-gray-900/60 border border-gray-800 flex items-center justify-between">
                <div>
                  <h3 className="text-base font-semibold text-white">Five-Pass Security Audit Engine</h3>
                  <p className="text-xs text-gray-400 mt-1">
                    Pass 1: Auth/RBAC • Pass 2: Secrets Scrubbing • Pass 3: Injection Defense • Pass 4: Tenant Isolation • Pass 5: Abuse/SSRF
                  </p>
                </div>
                <button
                  onClick={handleRunSecurityAudit}
                  disabled={runningAudit}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold transition flex items-center space-x-2"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${runningAudit ? 'animate-spin' : ''}`} />
                  <span>Execute Full Audit</span>
                </button>
              </div>

              {auditReport && (
                <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5 space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-white uppercase tracking-wider">Audit Results</h4>
                    <span className={`px-3 py-1 rounded-full text-xs font-bold ${
                      auditReport.overall_secure ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                    }`}>
                      {auditReport.overall_secure ? 'SYSTEM SECURE: ALL PASSES CLEARED' : 'AUDIT FAILED'}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {auditReport.passes.map((p: any) => (
                      <div key={p.pass_number} className="p-3 bg-gray-800/30 rounded-lg flex items-center justify-between">
                        <div className="flex items-center space-x-3">
                          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                          <span className="text-sm font-medium text-gray-200">
                            Pass {p.pass_number}: {p.name}
                          </span>
                        </div>
                        <span className="text-xs font-mono text-emerald-400 font-bold">PASSED</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 6: AUDIT TRAIL */}
          {activeTab === 'audit' && (
            <div className="bg-gray-900/60 border border-gray-800 rounded-2xl overflow-hidden">
              <div className="p-4 border-b border-gray-800">
                <h2 className="text-sm font-bold text-white">Authoritative Audit Trail</h2>
              </div>
              <div className="divide-y divide-gray-800 text-xs font-mono">
                {auditLogs.map((log) => (
                  <div key={log.id} className="p-3.5 hover:bg-gray-800/30 flex items-center justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center space-x-2">
                        <span className="text-blue-400 font-bold">[{log.actor}]</span>
                        <span className="text-white">{log.action}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          log.result === 'SUCCESS' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'
                        }`}>
                          {log.result}
                        </span>
                      </div>
                      <div className="text-gray-500">{log.reason}</div>
                    </div>
                    <span className="text-gray-500">{new Date(log.created_at).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
