import { useState, useEffect } from 'react';
import {
    Users, Package, Settings, MessageSquare, Activity,
    TrendingUp, Plus, Clock, ChevronRight, Zap, Bot,
    ArrowUpRight, AlertCircle, CheckCircle2, Cpu,
    Terminal, Brain, Shield, LayoutGrid, Sparkles, UserCheck
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import LoadingView from '../components/LoadingView';
import { HitlPanel } from './HitlComponents';

const StatCard = ({ icon: Icon, label, value, subValue, color, onClick }) => (
    <div
        onClick={onClick}
        className="dashboard-card"
        style={{
            background: 'white',
            padding: '20px',
            borderRadius: '16px',
            border: '1px solid #eef0f2',
            cursor: onClick ? 'pointer' : 'default',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            transition: 'transform 0.2s, box-shadow 0.2s',
        }}
    >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{
                width: '36px',
                height: '36px',
                background: `${color}15`,
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: color
            }}>
                <Icon size={18} />
            </div>
            {onClick && <ArrowUpRight size={14} color="#94a3b8" />}
        </div>

        <div>
            <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginBottom: '2px' }}>{label}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                <span style={{ fontSize: '20px', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.01em' }}>{value}</span>
                {subValue && <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 500 }}>{subValue}</span>}
            </div>
        </div>
    </div>
);

const QuickAction = ({ icon: Icon, label, desc, onClick, color }) => (
    <div
        onClick={onClick}
        onMouseOver={(e) => e.currentTarget.style.borderColor = color}
        onMouseOut={(e) => e.currentTarget.style.borderColor = '#eef0f2'}
        style={{
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
            padding: '16px',
            background: 'white',
            borderRadius: '12px',
            border: '1px solid #eef0f2',
            cursor: 'pointer',
            transition: 'all 0.2s'
        }}
    >
        <div style={{
            minWidth: '40px',
            height: '40px',
            background: '#f8fafc',
            borderRadius: '10px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: color
        }}>
            <Icon size={20} />
        </div>
        <div style={{ flex: 1 }}>
            <div style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>{label}</div>
            <div style={{ fontSize: '12px', color: '#64748b' }}>{desc}</div>
        </div>
        <ChevronRight size={16} color="#cbd5e1" />
    </div>
);

export default function Dashboard() {
    const navigate = useNavigate();
    const [stats, setStats] = useState(null);
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [currentTime, setCurrentTime] = useState(new Date());
    const [statusData, setStatusData] = useState({ online: true, daemon: { running: false } });
    const [user, setUser] = useState(null);
    const [hitlRequests, setHitlRequests] = useState([]);
    const [isHitlModalOpen, setIsHitlModalOpen] = useState(false);

    useEffect(() => {
        const timer = setInterval(() => setCurrentTime(new Date()), 1000);
        return () => clearInterval(timer);
    }, []);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [statsRes, sessionsRes, pingRes, daemonRes] = await Promise.all([
                    fetch('/api/stats'),
                    fetch('/api/sessions'),
                    fetch('/api/ping'),
                    fetch('/api/daemon/status')
                ]);

                const statsData = await statsRes.json();
                const sessionsData = await sessionsRes.json();
                const pingData = await pingRes.json().catch(() => ({ status: 'ok', user: null }));
                const daemonData = await daemonRes.json().catch(() => ({ running: false }));
                setUser(pingData.user || null);

                // Process stats
                if (statsData.tokens_by_model && !statsData.total_tokens) {
                    let input = 0, output = 0, total = 0;
                    Object.values(statsData.tokens_by_model).forEach(m => {
                        input += (m.input_tokens || 0);
                        output += (m.output_tokens || 0);
                        total += (m.total_tokens || 0);
                    });
                    statsData.total_tokens = total;
                    statsData.total_input_tokens = input;
                    statsData.total_output_tokens = output;
                }

                setStats(statsData);
                // Sort by most recent
                setSessions(Array.isArray(sessionsData)
                    ? [...sessionsData].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)).slice(0, 5)
                    : []);
                setStatusData({ online: pingRes.ok, daemon: daemonData });
                setLoading(false);
            } catch (err) {
                console.error("Fetch dashboard data error:", err);
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    const openHitlList = async () => {
        setIsHitlModalOpen(true);
        try {
            const res = await fetch('/api/hitl');
            const data = await res.json();
            setHitlRequests(data);
        } catch (e) {
            console.error("Failed to load HITL reqs", e);
        }
    };

    const handleHitlResolve = async (hitlId, resolution) => {
        try {
            await fetch(`/api/hitl/${hitlId}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(resolution)
            });
            setHitlRequests(prev => prev.filter(r => r.hitl_id !== hitlId));

            const statsRes = await fetch('/api/stats');
            const statsData = await statsRes.json();
            if (statsData) {
                setStats(prev => ({ ...prev, pending_hitl_count: statsData.pending_hitl_count }));
            }
            if (hitlRequests.length <= 1) setIsHitlModalOpen(false);
        } catch (error) {
            console.error('Failed to resolve HITL:', error);
        }
    };

    if (loading) return <LoadingView message="Assembling components..." />;
    if (!stats) return <div style={{ padding: '40px', color: '#ef4444' }}>Error synchronizing with core system.</div>;

    const hour = currentTime.getHours();
    const greeting = hour < 12 ? 'Good Morning' : hour < 18 ? 'Good Afternoon' : 'Good Evening';

    return (
        <div style={{ flex: 1, height: '100vh', overflowY: 'auto', background: '#f8fafc', padding: '32px 40px' }}>
            <style>{`
                .dashboard-card:hover {
                    transform: translateY(-4px);
                    box-shadow: 0 12px 20px -5px rgba(0, 0, 0, 0.1), 0 8px 8px -5px rgba(0, 0, 0, 0.04) !important;
                }
                @keyframes pulse-soft {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.6; }
                }
            `}</style>

            <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
                {/* Header Section */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '40px' }}>
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#6366f1', fontWeight: 700, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '8px' }}>
                            <Sparkles size={14} />
                            System Pulse Alpha
                        </div>
                        <h1 style={{ fontSize: '32px', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.02em', marginBottom: '4px' }}>
                            {greeting}, {user ? (user.name || user.email || 'Commander') : 'Commander'}
                        </h1>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                            <div style={{ fontSize: '14px', color: '#64748b', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <Clock size={14} />
                                {currentTime.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })} • {currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: statusData.online ? '#10b981' : '#ef4444' }}>
                                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: statusData.online ? '#10b981' : '#ef4444', animation: statusData.online ? 'pulse-soft 2s infinite' : 'none' }} />
                                {statusData.online ? 'System Operational' : 'Connection Disrupted'}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Top Metrics Row */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '20px', marginBottom: '32px' }}>
                    <StatCard
                        icon={Bot}
                        label="Active Agents"
                        value={stats.agents_count || 0}
                        subValue="Deployed Specs"
                        color="#6366f1"
                        onClick={() => navigate('/agents')}
                    />
                    <StatCard
                        icon={AlertCircle}
                        label="Pending Decisions"
                        value={stats.pending_hitl_count || 0}
                        subValue="Awaiting Approval"
                        color={stats.pending_hitl_count > 0 ? "#f43f5e" : "#94a3b8"}
                        onClick={() => navigate('/sessions?status=waiting_for_human')}
                    />
                    <StatCard
                        icon={Brain}
                        label="Skill Registry"
                        value={stats.skills_count || 0}
                        subValue="Dynamic Modules"
                        color="#0ea5e9"
                        onClick={() => navigate('/skills')}
                    />
                    <StatCard
                        icon={Activity}
                        label="Active Sessions"
                        value={stats.total_sessions || 0}
                        subValue="Total History"
                        color="#10b981"
                        onClick={() => navigate('/sessions')}
                    />
                </div>

                {/* Main Content Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 2fr', gap: '32px' }}>

                    {/* Left Column: Actions & Alerts */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>

                        {/* HITL Notice */}
                        {stats.pending_hitl_count > 0 && (
                            <div
                                className="dashboard-card"
                                onClick={openHitlList}
                                style={{
                                    background: 'white',
                                    border: '1px solid #eef0f2',
                                    padding: '16px 20px',
                                    borderRadius: '16px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '16px',
                                    cursor: 'pointer',
                                    boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                                    transition: 'transform 0.2s, box-shadow 0.2s'
                                }}
                            >
                                <div style={{ width: '40px', height: '40px', background: '#fff1f2', border: '1px solid #ffe4e6', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f43f5e', flexShrink: 0 }}>
                                    <AlertCircle size={20} />
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '14px', marginBottom: '2px' }}>Decision Required</div>
                                    <div style={{ color: '#64748b', fontSize: '12px' }}>{stats.pending_hitl_count} item{stats.pending_hitl_count > 1 ? 's' : ''} awaiting human review.</div>
                                </div>
                                <ChevronRight size={18} color="#94a3b8" />
                            </div>
                        )}

                        {/* Quick Actions (Quick Launch) */}
                        <div style={{ background: 'white', borderRadius: '16px', border: '1px solid #eef0f2', padding: '24px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px' }}>
                                <Zap size={18} color="#6366f1" />
                                <h2 style={{ fontSize: '16px', fontWeight: 700, color: '#0f172a' }}>Quick Launch</h2>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                <QuickAction
                                    icon={Sparkles}
                                    label="Design New Agent"
                                    desc="Converse with the Agent Architect"
                                    color="#6366f1"
                                    onClick={() => navigate('/sessions?agent_uuid=builtin_agent_creator')}
                                />
                                <QuickAction
                                    icon={Cpu}
                                    label="Create New Skill"
                                    desc="Implement custom logic modules"
                                    color="#0ea5e9"
                                    onClick={() => navigate('/sessions?agent_uuid=builtin_skill_creator')}
                                />
                                <QuickAction
                                    icon={Terminal}
                                    label="Tool Store"
                                    desc="Browse available system capabilities"
                                    color="#10b981"
                                    onClick={() => navigate('/tools')}
                                />
                            </div>
                        </div>
                    </div>

                    {/* Right Column: Activity & Resources */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>

                        {/* Recent Sessions & Resources Combined */}
                        <div style={{ background: 'white', borderRadius: '16px', border: '1px solid #eef0f2', padding: '24px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <Clock size={18} color="#64748b" />
                                    <h2 style={{ fontSize: '16px', fontWeight: 700, color: '#0f172a' }}>Recent Activity & Resources</h2>
                                </div>
                                <button onClick={() => navigate('/sessions')} style={{ padding: '6px 12px', background: '#f1f5f9', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: 600, color: '#475569', cursor: 'pointer' }}>View All</button>
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                {sessions.map(session => (
                                    <div
                                        key={session.session_id}
                                        onClick={() => navigate(`/sessions/${session.session_id}`)}
                                        style={{
                                            padding: '10px 12px',
                                            borderRadius: '10px',
                                            border: '1px solid #f1f5f9',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '12px',
                                            cursor: 'pointer',
                                            transition: 'background 0.2s'
                                        }}
                                        onMouseOver={(e) => e.currentTarget.style.background = '#f8fafc'}
                                        onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
                                    >
                                        <div style={{
                                            width: '32px',
                                            height: '32px',
                                            background: session.status === 'completed' ? '#f0fdf4' : (session.status === 'running' ? '#eff6ff' : '#fef2f2'),
                                            borderRadius: '6px',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center'
                                        }}>
                                            {session.status === 'completed' ? <CheckCircle2 size={16} color="#10b981" /> : (session.status === 'running' ? <Activity size={16} color="#3b82f6" /> : <AlertCircle size={16} color="#f43f5e" />)}
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: '13px', fontWeight: 600, color: '#1e293b' }}>{session.agent_name}</div>
                                            <div style={{ fontSize: '11px', color: '#94a3b8' }}>{new Date(session.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {session.session_id.slice(0, 8)}</div>
                                        </div>
                                        <div style={{
                                            padding: '3px 6px',
                                            borderRadius: '4px',
                                            fontSize: '9px',
                                            fontWeight: 700,
                                            textTransform: 'uppercase',
                                            background: session.status === 'completed' ? '#dcfce7' : (session.status === 'running' ? '#dbeafe' : '#fee2e2'),
                                            color: session.status === 'completed' ? '#166534' : (session.status === 'running' ? '#1e40af' : '#991b1b')
                                        }}>
                                            {session.status}
                                        </div>
                                    </div>
                                ))}
                                {sessions.length === 0 && <div style={{ textAlign: 'center', padding: '20px', color: '#94a3b8', fontSize: '14px' }}>No entries found.</div>}
                            </div>

                            <div style={{ marginTop: '24px', paddingTop: '24px', borderTop: '1px solid #eef0f2' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                                    <TrendingUp size={16} color="#64748b" />
                                    <h3 style={{ fontSize: '14px', fontWeight: 700, color: '#334155' }}>Resource Usage</h3>
                                </div>

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                    <div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                            <div style={{ fontSize: '11px', color: '#64748b', fontWeight: 700 }}>AGGREGATE TOKENS</div>
                                            <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>{(stats.total_tokens || 0).toLocaleString()}</div>
                                        </div>
                                        <div style={{ height: '6px', background: '#f1f5f9', borderRadius: '3px', display: 'flex', overflow: 'hidden' }}>
                                            <div style={{ width: `${stats.total_tokens ? (stats.total_input_tokens / stats.total_tokens) * 100 : 0}%`, background: '#6366f1' }}></div>
                                            <div style={{ width: `${stats.total_tokens ? (stats.total_output_tokens / stats.total_tokens) * 100 : 0}%`, background: '#818cf8' }}></div>
                                        </div>
                                    </div>

                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                        <div style={{ padding: '10px', background: '#f8fafc', borderRadius: '10px', border: '1px solid #f1f5f9' }}>
                                            <div style={{ fontSize: '9px', color: '#94a3b8', fontWeight: 700, marginBottom: '2px' }}>TOOL CALLS</div>
                                            <div style={{ fontSize: '16px', fontWeight: 800, color: '#0f172a' }}>{(stats.total_tool_calls || 0).toLocaleString()}</div>
                                        </div>
                                        <div style={{ padding: '10px', background: '#f8fafc', borderRadius: '10px', border: '1px solid #f1f5f9' }}>
                                            <div style={{ fontSize: '9px', color: '#94a3b8', fontWeight: 700, marginBottom: '2px' }}>ERRORS</div>
                                            <div style={{ fontSize: '16px', fontWeight: 800, color: stats.total_errors > 0 ? '#ef4444' : '#0f172a' }}>{stats.total_errors || 0}</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* HITL Requests Modal */}
            <Modal
                isOpen={isHitlModalOpen}
                onClose={() => setIsHitlModalOpen(false)}
                title="Pending Decisions"
                width="700px"
                footer={
                    <button
                        onClick={() => setIsHitlModalOpen(false)}
                        style={{
                            padding: '8px 16px',
                            borderRadius: '6px',
                            border: '1px solid #e5e7eb',
                            background: 'white',
                            color: '#374151',
                            cursor: 'pointer',
                            fontWeight: 500
                        }}
                    >
                        Close
                    </button>
                }
            >
                <div style={{ maxHeight: '60vh', overflowY: 'auto', paddingRight: '4px' }}>
                    <HitlPanel
                        requests={hitlRequests}
                        onResolve={handleHitlResolve}
                    />
                </div>
            </Modal>
        </div>
    );
}

// Reusable Modal Component
const Modal = ({ isOpen, onClose, title, children, footer, width = '400px' }) => {
    if (!isOpen) return null;
    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
        }} onClick={onClose}>
            <div style={{
                background: 'white', borderRadius: '12px', width: width, maxWidth: '95%',
                padding: '24px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)'
            }} onClick={e => e.stopPropagation()}>
                <div style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px', color: '#1f2937' }}>{title}</div>
                <div style={{ marginBottom: '24px', color: '#4b5563', fontSize: '14px', lineHeight: '1.5' }}>{children}</div>
                {footer && <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '24px' }}>{footer}</div>}
            </div>
        </div>
    );
};
