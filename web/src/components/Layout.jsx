import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Layers, MessageSquare, Box, Settings, Users, Plus, Package, Activity, ChevronLeft, ChevronRight, BookOpen, Database, Brain, Bot, Sparkles, Cpu, Wand2, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function Layout({ children }) {
    const location = useLocation();
    const [isCollapsed, setIsCollapsed] = useState(() => {
        return localStorage.getItem('sidebarCollapsed') === 'true';
    });
    const [isOnline, setIsOnline] = useState(true);
    const [daemonStatus, setDaemonStatus] = useState({ enabled: false, running: false });
    const [daemonLoops, setDaemonLoops] = useState({});
    const [hitlCount, setHitlCount] = useState(0);
    const [reconnectTrigger, setReconnectTrigger] = useState(0);
    const [quickHelpersOpen, setQuickHelpersOpen] = useState(false);
    const navigate = useNavigate();

    const navItems = [
        { icon: Layers, label: 'Dashboard', path: '/' },
        { icon: Bot, label: 'Agents', path: '/agents' },
        { icon: MessageSquare, label: 'Sessions', path: '/sessions' },
        { icon: Package, label: 'Skills', path: '/skills' },
        { icon: Box, label: 'MCP', path: '/mcp' },
        { icon: Settings, label: 'Tools', path: '/tools' },
        { icon: BookOpen, label: 'Knowledge', path: '/knowledge' },
        { icon: Activity, label: 'Tracing', path: '/tracing' },
        { icon: Settings, label: 'Settings', path: '/settings' },
    ];

    useEffect(() => {
        localStorage.setItem('sidebarCollapsed', isCollapsed);
    }, [isCollapsed]);

    useEffect(() => {
        const checkHealth = () => {
            fetch('/api/ping')
                .then(res => setIsOnline(res.ok))
                .catch(() => setIsOnline(false));

            fetch('/api/daemon/status')
                .then(res => res.json())
                .then(data => setDaemonStatus(data))
                .catch(() => { });

            fetch('/api/daemon/loops')
                .then(res => res.json())
                .then(data => setDaemonLoops(data.loops || {}))
                .catch(() => { });
        };
        checkHealth();
        const timer = setInterval(checkHealth, 10000);
        return () => clearInterval(timer);
    }, []);

    // HITL Global State
    useEffect(() => {
        const fetchHitl = () => {
            fetch('/api/hitl')
                .then(res => res.json())
                .then(data => setHitlCount(data.length))
                .catch(() => { });
        };
        fetchHitl();

        const _wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${_wsProto}//${window.location.host}/api/ws`);
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'hitl_requested' || data.type === 'hitl_resolved') {
                    fetchHitl();
                }
            } catch (e) { }
        };
        ws.onclose = (event) => {
            if (!event.wasClean) {
                console.log("Global WS lost, retrying in 5s...");
                setTimeout(() => setReconnectTrigger(prev => prev + 1), 5000);
            }
        };
        return () => ws.close();
    }, [reconnectTrigger]);

    return (
        <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
            {/* Sidebar Navigation */}
            <aside style={{
                width: isCollapsed ? '72px' : '240px',
                background: 'white',
                borderRight: '1px solid #e5e7eb',
                display: 'flex',
                flexDirection: 'column',
                transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                position: 'relative'
            }}>
                <div style={{ padding: '24px', display: 'flex', alignItems: 'center', gap: '12px', overflow: 'hidden' }}>
                    <div style={{ minWidth: '32px', height: '32px', background: '#111827', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                        <Bot color="white" size={20} />
                    </div>
                    {!isCollapsed && (
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                            <span style={{ fontWeight: 800, fontSize: '18px', letterSpacing: '-0.5px', whiteSpace: 'nowrap', lineHeight: 1 }}>EVERSTAFF</span>
                            <span style={{ fontSize: '10px', color: '#6b7280', fontWeight: 600, letterSpacing: '0.05em', marginTop: '2px' }}>AI AGENT OS</span>
                        </div>
                    )}
                </div>

                <nav style={{ flex: 1, padding: '0 12px' }}>
                    {navItems.map((item) => {
                        const Icon = item.icon;
                        const isActive = location.pathname === item.path || (item.path !== '/' && location.pathname.startsWith(item.path));

                        return (
                            <Link
                                key={item.path}
                                to={item.path}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '12px',
                                    padding: '10px 12px',
                                    borderRadius: '6px',
                                    textDecoration: 'none',
                                    color: isActive ? '#111827' : '#6b7280',
                                    background: isActive ? '#f3f4f6' : 'transparent',
                                    fontWeight: isActive ? 600 : 500,
                                    fontSize: '14px',
                                    marginBottom: '4px',
                                    transition: 'all 0.15s',
                                    justifyContent: isCollapsed ? 'center' : 'flex-start'
                                }}
                                title={isCollapsed ? item.label : ''}
                            >
                                <Icon size={18} />
                                {!isCollapsed && <span style={{ flex: 1 }}>{item.label}</span>}
                                {!isCollapsed && item.label === 'Sessions' && hitlCount > 0 && (
                                    <span style={{
                                        background: '#ef4444',
                                        color: 'white',
                                        fontSize: '10px',
                                        fontWeight: 800,
                                        padding: '2px 6px',
                                        borderRadius: '10px',
                                        marginLeft: 'auto'
                                    }}>
                                        {hitlCount}
                                    </span>
                                )}
                                {isCollapsed && item.label === 'Sessions' && hitlCount > 0 && (
                                    <div style={{
                                        position: 'absolute',
                                        top: '6px',
                                        right: '6px',
                                        width: '8px',
                                        height: '8px',
                                        background: '#ef4444',
                                        borderRadius: '50%',
                                        border: '2px solid white'
                                    }} />
                                )}
                            </Link>
                        );
                    })}
                </nav>

                <div style={{ padding: '16px', borderTop: '1px solid #f3f4f6', overflow: 'hidden' }}>
                    {/* New Collapse Toggle Position */}
                    <button
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        style={{
                            width: '100%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: isCollapsed ? 'center' : 'space-between',
                            padding: '8px',
                            background: 'transparent',
                            border: 'none',
                            color: '#9ca3af',
                            cursor: 'pointer',
                            borderRadius: '6px',
                            transition: 'background 0.2s',
                            marginBottom: '12px'
                        }}
                        onMouseOver={(e) => e.currentTarget.style.background = '#f9fafb'}
                        onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
                        title={isCollapsed ? "Expand Sidebar" : "Collapse Sidebar"}
                    >
                        {!isCollapsed && <span style={{ fontSize: '12px', fontWeight: 600 }}>COLLAPSE</span>}
                        {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                    </button>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', justifyContent: isCollapsed ? 'center' : 'flex-start', marginBottom: '12px' }}>
                        <div style={{
                            minWidth: '8px',
                            height: '8px',
                            borderRadius: '50%',
                            background: !daemonStatus.enabled ? '#9ca3af' : (daemonStatus.running ? '#10b981' : '#ef4444'),
                            boxShadow: daemonStatus.running ? '0 0 8px #10b981' : 'none'
                        }}></div>
                        {!isCollapsed && (
                            <div style={{ display: 'flex', flexDirection: 'column' }}>
                                <span style={{ fontSize: '11px', color: '#9ca3af', fontWeight: 700, letterSpacing: '0.05em' }}>DAEMON</span>
                                <span style={{ color: '#4b5563', fontWeight: 500 }}>
                                    {!daemonStatus.enabled ? 'Disabled' : (daemonStatus.running ? 'Running' : 'Stopped')}
                                </span>
                            </div>
                        )}
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', justifyContent: isCollapsed ? 'center' : 'flex-start' }}>
                        <div style={{ minWidth: '8px', height: '8px', borderRadius: '50%', background: isOnline ? '#10b981' : '#ef4444' }}></div>
                        {!isCollapsed && (
                            <div style={{ display: 'flex', flexDirection: 'column' }}>
                                <span style={{ fontSize: '11px', color: '#9ca3af', fontWeight: 700, letterSpacing: '0.05em' }}>API STATUS</span>
                                <span style={{ color: '#4b5563', fontWeight: 500 }}>{isOnline ? 'Operational' : 'Offline'}</span>
                            </div>
                        )}
                    </div>
                </div>
            </aside>

            {/* Main Content Area */}
            <main style={{ flex: 1, background: '#f9fafb', height: '100vh', overflow: 'hidden', position: 'relative' }}>
                {children}

                {/* Global Quick Assistants (Bottom Left of Main Content) */}
                <div style={{ position: 'absolute', bottom: '24px', left: '24px', zIndex: 100, display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '12px' }}>
                    {quickHelpersOpen && (
                        <div style={{
                            background: 'white',
                            borderRadius: '12px',
                            boxShadow: '0 10px 25px rgba(0,0,0,0.1), 0 4px 6px rgba(0,0,0,0.05)',
                            border: '1px solid #e5e7eb',
                            overflow: 'hidden',
                            width: '240px',
                            animation: 'slideUp 0.2s cubic-bezier(0.16, 1, 0.3, 1)'
                        }}>
                            <div style={{ padding: '12px 16px', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#f8fafc' }}>
                                <span style={{ fontSize: '12px', fontWeight: 700, color: '#475569', letterSpacing: '0.05em' }}>QUICK ASSISTANTS</span>
                                <X size={14} color="#94a3b8" style={{ cursor: 'pointer' }} onClick={() => setQuickHelpersOpen(false)} />
                            </div>
                            <div style={{ padding: '8px' }}>
                                <div
                                    className="quick-helper-btn"
                                    style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 12px', borderRadius: '8px', cursor: 'pointer', transition: 'background 0.2s' }}
                                    onMouseOver={e => e.currentTarget.style.background = '#f1f5f9'}
                                    onMouseOut={e => e.currentTarget.style.background = 'transparent'}
                                    onClick={() => { setQuickHelpersOpen(false); navigate('/sessions?agent_uuid=builtin_agent_creator'); }}
                                >
                                    <div style={{ background: '#eff6ff', padding: '6px', borderRadius: '6px', color: '#3b82f6' }}><Bot size={16} /></div>
                                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                                        <span style={{ fontSize: '13px', fontWeight: 600, color: '#1e293b' }}>Agent Architect</span>
                                        <span style={{ fontSize: '11px', color: '#64748b' }}>Design new agents</span>
                                    </div>
                                </div>
                                <div
                                    className="quick-helper-btn"
                                    style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 12px', borderRadius: '8px', cursor: 'pointer', transition: 'background 0.2s' }}
                                    onMouseOver={e => e.currentTarget.style.background = '#f1f5f9'}
                                    onMouseOut={e => e.currentTarget.style.background = 'transparent'}
                                    onClick={() => { setQuickHelpersOpen(false); navigate('/sessions?agent_uuid=builtin_skill_creator'); }}
                                >
                                    <div style={{ background: '#fef2f2', padding: '6px', borderRadius: '6px', color: '#ef4444' }}><Cpu size={16} /></div>
                                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                                        <span style={{ fontSize: '13px', fontWeight: 600, color: '#1e293b' }}>Skill Forge</span>
                                        <span style={{ fontSize: '11px', color: '#64748b' }}>Create custom capabilities</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    <button
                        onClick={() => setQuickHelpersOpen(!quickHelpersOpen)}
                        style={{
                            width: '44px',
                            height: '44px',
                            borderRadius: '50%',
                            background: '#111827',
                            color: 'white',
                            border: 'none',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            boxShadow: '0 4px 12px rgba(17, 24, 39, 0.25)',
                            transition: 'all 0.2s',
                            transform: quickHelpersOpen ? 'scale(0.95)' : 'scale(1)'
                        }}
                        onMouseOver={e => !quickHelpersOpen && (e.currentTarget.style.transform = 'scale(1.05)')}
                        onMouseOut={e => !quickHelpersOpen && (e.currentTarget.style.transform = 'scale(1)')}
                        title="Quick Assistants"
                    >
                        <Sparkles size={20} />
                    </button>
                </div>
            </main>
            <style>{`
                @keyframes slideUp {
                    from { opacity: 0; transform: translateY(10px); }
                    to { opacity: 1; transform: translateY(0); }
                }
            `}</style>
        </div>
    );
}
