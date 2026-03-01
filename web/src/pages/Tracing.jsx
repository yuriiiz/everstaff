import { useState, useEffect } from 'react';
import { Activity, Clock, Search, ChevronRight, FileJson, AlertCircle, Terminal, Bot, User, Package } from 'lucide-react';
import LoadingView from '../components/LoadingView';
import { useSearchParams } from 'react-router-dom';

const EventIcon = ({ type }) => {
    switch (type) {
        case 'llm_start':
        case 'llm_end':
            return <Bot size={14} color="#3b82f6" />;
        case 'tool_start':
        case 'tool_end':
            return <Terminal size={14} color="#10b981" />;
        case 'error':
            return <AlertCircle size={14} color="#ef4444" />;
        case 'session_start':
        case 'session_end':
            return <Clock size={14} color="#6b7280" />;
        case 'sub_session_start':
            return <Package size={14} color="#8b5cf6" />;
        default:
            return <Activity size={14} color="#6b7280" />;
    }
};

const TraceDetail = ({ event, onClose }) => {
    if (!event) return null;

    return (
        <div style={{
            width: '400px',
            background: 'white',
            borderLeft: '1px solid #e5e7eb',
            display: 'flex',
            flexDirection: 'column',
            height: '100vh',
            position: 'sticky',
            top: 0
        }}>
            <div style={{ padding: '16px', borderBottom: '1px solid #f3f4f6', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ fontSize: '14px', fontWeight: 700, color: '#111827' }}>Event Details</h3>
                <button onClick={onClose} style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#6b7280' }}>×</button>
            </div>
            <div style={{ padding: '16px', overflowY: 'auto', flex: 1 }}>
                <div style={{ marginBottom: '16px' }}>
                    <div style={{ fontSize: '11px', color: '#6b7280', fontWeight: 600, marginBottom: '4px' }}>TYPE</div>
                    <div style={{ fontSize: '13px', color: '#111827', fontWeight: 500 }}>{event.type}</div>
                </div>
                <div style={{ marginBottom: '16px' }}>
                    <div style={{ fontSize: '11px', color: '#6b7280', fontWeight: 600, marginBottom: '4px' }}>TIMESTAMP</div>
                    <div style={{ fontSize: '13px', color: '#111827' }}>{new Date(event.timestamp).toLocaleString()}</div>
                </div>
                <div style={{ marginBottom: '16px' }}>
                    <div style={{ fontSize: '11px', color: '#6b7280', fontWeight: 600, marginBottom: '4px' }}>SESSION ID</div>
                    <div style={{ fontSize: '12px', color: '#111827', fontFamily: 'monospace' }}>{event.session_id}</div>
                </div>
                <div>
                    <div style={{ fontSize: '11px', color: '#6b7280', fontWeight: 600, marginBottom: '4px' }}>PAYLOAD</div>
                    <pre style={{
                        fontSize: '11px',
                        background: '#f8fafc',
                        padding: '12px',
                        borderRadius: '6px',
                        overflowX: 'auto',
                        border: '1px solid #e2e8f0',
                        color: '#334155'
                    }}>
                        {JSON.stringify(event, null, 2)}
                    </pre>
                </div>
            </div>
        </div>
    );
};

export default function Tracing() {
    const [searchParams] = useSearchParams();
    const [traces, setTraces] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');
    const [searchSessionId, setSearchSessionId] = useState('');
    const [searchToolName, setSearchToolName] = useState('');
    const [searchAgentName, setSearchAgentName] = useState(searchParams.get('agent_name') || '');
    const [selectedEvent, setSelectedEvent] = useState(null);

    useEffect(() => {
        fetchTraces();
    }, []);

    const fetchTraces = () => {
        setLoading(true);
        fetch('/api/traces?limit=500')
            .then(res => res.json())
            .then(data => {
                const arrayData = Array.isArray(data) ? data : (data.traces || []);
                // New Schema Normalization
                const normalized = arrayData.map(item => {
                    const type = item.kind || item.type || 'unknown';
                    const payload = item.data || {};
                    return {
                        ...item,
                        type,
                        // Extract common display fields from new 'data' payload
                        display_content: payload.content || (payload.response?.content) || payload.error || payload.prompt || '',
                        model_name: payload.model || (payload.response?.model) || item.model || '-',
                        tokens: (payload.input_tokens || 0) + (payload.output_tokens || 0) || item.usage?.total_tokens || 0,
                        agent_name: payload.agent_name || item.agent_name || '-',
                        tool_name: payload.tool_name || item.tool_name || '-'
                    };
                });
                setTraces(normalized);
                setLoading(false);
            })
            .catch(err => {
                console.error('Failed to fetch traces:', err);
                setLoading(false);
            });
    };

    const filteredTraces = traces.filter(t => {
        // 1. Type Filter
        if (filter !== 'all') {
            const matchesType = (filter === 'llm' && t.type.startsWith('llm_')) ||
                (filter === 'tool' && t.type.startsWith('tool_')) ||
                (filter === 'error' && t.type === 'error') ||
                (t.type === filter);
            if (!matchesType) return false;
        }

        // 2. Session ID Search
        if (searchSessionId && !t.session_id?.toLowerCase().includes(searchSessionId.toLowerCase())) {
            return false;
        }

        // 3. Tool Name Search
        if (searchToolName) {
            const toolName = t.tool_name || (t.type === 'tool_start' ? t.tool_name : '');
            if (!toolName?.toLowerCase().includes(searchToolName.toLowerCase())) {
                return false;
            }
        }

        // 4. Agent Name Search
        if (searchAgentName && !t.agent_name?.toLowerCase().includes(searchAgentName.toLowerCase())) {
            return false;
        }

        return true;
    });

    return (
        <div style={{ flex: 1, background: '#f9fafb', height: '100vh', display: 'flex' }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {/* Header */}
                <div style={{ padding: '20px 32px', borderBottom: '1px solid #e5e7eb', background: 'white' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <div>
                            <h1 style={{ fontSize: '20px', fontWeight: 700, color: '#111827' }}>System Audit Logs</h1>
                            <p style={{ color: '#6b7280', fontSize: '13px' }}>Monitor and audit framework events and LLM traces</p>
                        </div>
                        <button
                            onClick={fetchTraces}
                            style={{
                                padding: '6px 16px',
                                background: '#111827',
                                color: 'white',
                                borderRadius: '6px',
                                border: 'none',
                                fontSize: '13px',
                                fontWeight: 600,
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '6px'
                            }}
                        >
                            <Activity size={14} /> Refresh
                        </button>
                    </div>

                    {/* Advanced Filters Bar */}
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#6b7280' }}>TYPE</span>
                            <select
                                value={filter}
                                onChange={(e) => setFilter(e.target.value)}
                                style={{
                                    padding: '6px 30px 6px 12px',
                                    borderRadius: '6px',
                                    border: '1px solid #e5e7eb',
                                    fontSize: '13px',
                                    color: '#374151',
                                    background: 'white',
                                    outline: 'none',
                                    appearance: 'none',
                                    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'%3E%3C/path%3E%3C/svg%3E")`,
                                    backgroundRepeat: 'no-repeat',
                                    backgroundPosition: 'right 8px center'
                                }}
                            >
                                <option value="all">All Events</option>
                                <option value="llm">LLM Activity</option>
                                <option value="tool">Tool Execution</option>
                                <option value="error">Errors</option>
                                <option value="session_start">Sessions</option>
                            </select>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, maxWidth: '300px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#6b7280' }}>SESSION</span>
                            <div style={{ position: 'relative', flex: 1 }}>
                                <Search size={14} color="#9ca3af" style={{ position: 'absolute', left: '10px', top: '9px' }} />
                                <input
                                    type="text"
                                    placeholder="Search Session ID..."
                                    value={searchSessionId}
                                    onChange={(e) => setSearchSessionId(e.target.value)}
                                    style={{
                                        width: '100%',
                                        padding: '6px 12px 6px 32px',
                                        borderRadius: '6px',
                                        border: '1px solid #e5e7eb',
                                        fontSize: '13px',
                                        outline: 'none'
                                    }}
                                />
                            </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, maxWidth: '250px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#6b7280' }}>TOOL</span>
                            <div style={{ position: 'relative', flex: 1 }}>
                                <Terminal size={14} color="#9ca3af" style={{ position: 'absolute', left: '10px', top: '9px' }} />
                                <input
                                    type="text"
                                    placeholder="Search Tool Name..."
                                    value={searchToolName}
                                    onChange={(e) => setSearchToolName(e.target.value)}
                                    style={{
                                        width: '100%',
                                        padding: '6px 12px 6px 32px',
                                        borderRadius: '6px',
                                        border: '1px solid #e5e7eb',
                                        fontSize: '13px',
                                        outline: 'none'
                                    }}
                                />
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, maxWidth: '250px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#6b7280' }}>AGENT</span>
                            <div style={{ position: 'relative', flex: 1 }}>
                                <User size={14} color="#9ca3af" style={{ position: 'absolute', left: '10px', top: '9px' }} />
                                <input
                                    type="text"
                                    placeholder="Search Agent..."
                                    value={searchAgentName}
                                    onChange={(e) => setSearchAgentName(e.target.value)}
                                    style={{
                                        width: '100%',
                                        padding: '6px 12px 6px 32px',
                                        borderRadius: '6px',
                                        border: '1px solid #e5e7eb',
                                        fontSize: '13px',
                                        outline: 'none'
                                    }}
                                />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Main List */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
                    {loading ? (
                        <LoadingView message="Loading Audit Logs..." fullScreen={false} />
                    ) : filteredTraces.length === 0 ? (
                        <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '60px', textAlign: 'center' }}>
                            <Activity size={40} color="#d1d5db" style={{ marginBottom: '12px' }} />
                            <h3 style={{ color: '#111827', fontWeight: 600 }}>No matching traces</h3>
                            <p style={{ color: '#6b7280', fontSize: '14px' }}>Try adjusting your search or filters.</p>
                        </div>
                    ) : (
                        <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: '8px', overflow: 'hidden' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                                <thead style={{ background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                                    <tr>
                                        <th style={{ padding: '12px 16px', fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase' }}>Type</th>
                                        <th style={{ padding: '12px 16px', fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase' }}>Event</th>
                                        <th style={{ padding: '12px 16px', fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase' }}>Time</th>
                                        <th style={{ padding: '12px 16px', fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase' }}>Session</th>
                                        <th style={{ padding: '12px 16px', fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', textAlign: 'right' }}>Tokens</th>
                                        <th style={{ padding: '12px 16px', width: '40px' }}></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredTraces.map((t, idx) => (
                                        <tr
                                            key={idx}
                                            onClick={() => setSelectedEvent(t)}
                                            style={{
                                                borderBottom: '1px solid #f3f4f6',
                                                cursor: 'pointer',
                                                background: selectedEvent === t ? '#f8fafc' : 'transparent',
                                                transition: 'background 0.1s'
                                            }}
                                            onMouseEnter={(e) => e.currentTarget.style.background = '#f9fafb'}
                                            onMouseLeave={(e) => e.currentTarget.style.background = selectedEvent === t ? '#f8fafc' : 'transparent'}
                                        >
                                            <td style={{ padding: '12px 16px' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                    <EventIcon type={t.type} />
                                                    <span style={{ fontSize: '12px', fontWeight: 500, color: '#374151', textTransform: 'capitalize' }}>
                                                        {t.type.replace('_', ' ')}
                                                    </span>
                                                </div>
                                            </td>
                                            <td style={{ padding: '12px 16px' }}>
                                                <div style={{ fontSize: '12px', color: '#111827', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {t.type === 'llm_start' && `Model: ${t.model_name}`}
                                                    {t.type === 'llm_end' && t.display_content}
                                                    {t.type === 'tool_start' && `Tool: ${t.tool_name}`}
                                                    {t.type === 'error' && t.display_content}
                                                    {t.type === 'session_start' && `Agent: ${t.agent_name}`}
                                                    {!['llm_start', 'llm_end', 'tool_start', 'error', 'session_start'].includes(t.type) && (t.display_content || '-')}
                                                </div>
                                            </td>
                                            <td style={{ padding: '12px 16px', fontSize: '12px', color: '#6b7280' }}>
                                                {new Date(t.timestamp).toLocaleTimeString()}
                                            </td>
                                            <td style={{ padding: '12px 16px' }}>
                                                <span title={t.session_id} style={{ fontSize: '11px', color: '#3b82f6', fontFamily: 'monospace' }}>
                                                    {t.session_id?.slice(0, 8)}...
                                                </span>
                                            </td>
                                            <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                                                {t.tokens > 0 ? (
                                                    <span style={{ fontSize: '12px', fontWeight: 600, color: '#111827' }}>
                                                        {t.tokens}
                                                    </span>
                                                ) : (
                                                    <span style={{ color: '#d1d5db' }}>-</span>
                                                )}
                                            </td>
                                            <td style={{ padding: '12px 16px' }}>
                                                <ChevronRight size={14} color="#d1d5db" />
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>

            {/* Detail Pane */}
            <TraceDetail
                event={selectedEvent}
                onClose={() => setSelectedEvent(null)}
            />
        </div>
    );
}
