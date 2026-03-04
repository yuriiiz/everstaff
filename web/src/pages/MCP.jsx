import { useState, useEffect } from 'react';
import { Search, Plus, Share2, Server, Shield, Check, X, AlertCircle, ExternalLink, Filter, ChevronRight, HardDrive, Package, Code, Trash2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import LoadingView from '../components/LoadingView';
import { useNavigate } from 'react-router-dom';
import Select from 'react-select';
import { Info as InfoIcon } from 'lucide-react';

export default function MCP() {
    const navigate = useNavigate();
    const [templates, setTemplates] = useState([]);
    const [agents, setAgents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [categoryFilter, setCategoryFilter] = useState('all');
    const [selectedTemplate, setSelectedTemplate] = useState(null);
    const [configEnv, setConfigEnv] = useState({});
    const [targetAgent, setTargetAgent] = useState('');
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [importJson, setImportJson] = useState(JSON.stringify({
        "name": "custom-server",
        "display_name": "My Custom Server",
        "description": "Describe your server here",
        "icon": "https://api.dicebear.com/7.x/shapes/svg?seed=mcp",
        "category": "utility",
        "transport": "stdio",
        "command": "npx",
        "args": ["@modelcontextprotocol/server-everything"],
        "env": {},
        "required_env": [
            { "name": "API_KEY", "description": "Required API Key", "required": true }
        ]
    }, null, 2));

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [tplRes, agentRes] = await Promise.all([
                    fetch('/api/mcp/templates'),
                    fetch('/api/agents')
                ]);
                const tplData = await tplRes.json();
                const agentData = await agentRes.json();
                setTemplates(tplData);
                setAgents(agentData);
                setLoading(false);
            } catch (err) {
                console.error("Fetch error:", err);
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    const filteredTemplates = templates.filter(t => {
        const matchesSearch = (t.display_name || t.name).toLowerCase().includes(searchQuery.toLowerCase()) ||
            t.description.toLowerCase().includes(searchQuery.toLowerCase());
        const matchesCategory = categoryFilter === 'all' || t.category === categoryFilter;
        return matchesSearch && matchesCategory;
    });

    const categories = ['all', ...new Set(templates.map(t => t.category).filter(Boolean))];

    const handleTemplateClick = (tpl) => {
        setSelectedTemplate(tpl);
        const initialEnv = {};
        (tpl.required_env || []).forEach(env => {
            initialEnv[env.key] = tpl.env?.[env.key] || '';
        });
        setConfigEnv(initialEnv);
        setTestResult(null);
        setTargetAgent('');
    };

    const handleTestConnection = async () => {
        setTesting(true);
        setTestResult(null);
        try {
            const res = await fetch('/api/mcp/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...selectedTemplate,
                    env: configEnv
                })
            });
            const data = await res.json();
            setTestResult(data);
        } catch (err) {
            setTestResult({ success: false, error: err.message });
        } finally {
            setTesting(false);
        }
    };

    const handleAddToAgent = async () => {
        if (!targetAgent) return;
        setSubmitting(true);
        try {
            const agent = agents.find(a => a.uuid === targetAgent || a.agent_name === targetAgent);
            const res = await fetch(`/api/agents/${agent.uuid}/mcp-servers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    template: selectedTemplate.name,
                    env: configEnv
                })
            });
            if (res.ok) {
                // Success toast or navigate
                navigate(`/agents?uuid=${agent.uuid}&sub=mcp`);
            } else {
                const data = await res.json();
                alert(data.error || "Failed to add MCP server");
            }
        } catch (err) {
            alert("Error: " + err.message);
        } finally {
            setSubmitting(false);
        }
    };

    if (loading) return <LoadingView message="Loading MCP Marketplace..." />;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#f9fafb' }}>
            {/* Header */}
            <div style={{ padding: '0 24px', background: 'white', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', height: '60px', flexShrink: 0 }}>
                <div>
                    <h1 style={{ fontSize: '15px', fontWeight: 700, color: '#111827', margin: 0 }}>MCP Marketplace</h1>
                </div>
                <div style={{ display: 'flex', gap: '12px' }}>
                    <button
                        onClick={() => setShowCreateModal(true)}
                        style={{
                            padding: '8px 16px', borderRadius: '8px', background: '#111827', color: 'white', border: 'none',
                            fontSize: '13px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px'
                        }}
                    >
                        <Plus size={16} /> Create Template
                    </button>
                </div>
            </div>

            {/* Filter Bar */}
            <div style={{ padding: '16px 24px', background: 'white', borderBottom: '1px solid #e5e7eb', display: 'flex', gap: '16px', alignItems: 'center' }}>
                <div style={{ position: 'relative', flex: 1, maxWidth: '400px' }}>
                    <Search style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#9ca3af' }} size={16} />
                    <input
                        type="text"
                        placeholder="Search templates..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        style={{
                            width: '100%', padding: '8px 12px 8px 36px', borderRadius: '8px', border: '1px solid #e5e7eb',
                            fontSize: '14px', outline: 'none'
                        }}
                    />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Filter size={14} color="#6b7280" />
                    <select
                        value={categoryFilter}
                        onChange={(e) => setCategoryFilter(e.target.value)}
                        style={{
                            padding: '8px 12px', borderRadius: '8px', border: '1px solid #e5e7eb', background: 'white',
                            fontSize: '14px', outline: 'none', color: '#374151'
                        }}
                    >
                        {categories.map(cat => (
                            <option key={cat} value={cat}>{cat.charAt(0).toUpperCase() + cat.slice(1)}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* Grid */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                    {filteredTemplates.map(tpl => (
                        <motion.div
                            key={tpl.name}
                            whileHover={{ y: -4, boxShadow: '0 12px 20px -5px rgba(0,0,0,0.1)' }}
                            onClick={() => handleTemplateClick(tpl)}
                            style={{
                                padding: '20px', background: 'white', borderRadius: '16px', border: '1px solid #e5e7eb',
                                cursor: 'pointer', transition: 'all 0.2s', display: 'flex', flexDirection: 'column', gap: '12px'
                            }}
                        >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div style={{
                                    width: '40px', height: '40px', borderRadius: '10px', background: '#f3f4f6',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden'
                                }}>
                                    {tpl.icon ? (
                                        <img src={tpl.icon} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="" />
                                    ) : (
                                        <Server size={20} color="#111827" />
                                    )}
                                </div>
                                <div style={{ display: 'flex', gap: '6px' }}>
                                    <span style={{
                                        padding: '2px 8px', borderRadius: '4px', background: '#fef3c7', color: '#92400e',
                                        fontSize: '10px', fontWeight: 700, textTransform: 'uppercase'
                                    }}>
                                        {tpl.category || 'Utility'}
                                    </span>
                                    {tpl.source === 'builtin' ? (
                                        <span style={{
                                            padding: '2px 8px', borderRadius: '4px', background: '#ecfdf5', color: '#065f46',
                                            fontSize: '10px', fontWeight: 700, textTransform: 'uppercase'
                                        }}>
                                            Built-in
                                        </span>
                                    ) : (
                                        <button
                                            onClick={async (e) => {
                                                e.stopPropagation();
                                                if (confirm(`Delete template ${tpl.display_name || tpl.name}?`)) {
                                                    try {
                                                        const res = await fetch(`/api/mcp/templates/${tpl.name}`, { method: 'DELETE' });
                                                        if (res.ok) {
                                                            setTemplates(prev => prev.filter(t => t.name !== tpl.name));
                                                        } else {
                                                            const err = await res.json();
                                                            alert(err.detail || "Failed to delete template");
                                                        }
                                                    } catch (e) { alert(e.message); }
                                                }
                                            }}
                                            style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#ef4444', padding: '4px', display: 'flex', alignItems: 'center' }}
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    )}
                                </div>
                            </div>
                            <div style={{ flex: 1 }}>
                                <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#111827', margin: '0 0 4px 0' }}>{tpl.display_name || tpl.name}</h3>
                                <p style={{ fontSize: '13px', color: '#6b7280', margin: 0, lineHeight: '1.5', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                                    {tpl.description}
                                </p>
                            </div>
                        </motion.div>
                    ))}
                </div>
            </div>

            {/* Template Config Panel (Drawer) */}
            <AnimatePresence>
                {selectedTemplate && (
                    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', justifyContent: 'flex-end' }}>
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            onClick={() => setSelectedTemplate(null)}
                            style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)', backdropFilter: 'blur(2px)' }}
                        />
                        <motion.div
                            initial={{ x: '100%' }}
                            animate={{ x: 0 }}
                            exit={{ x: '100%' }}
                            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                            style={{
                                width: '480px', height: '100%', background: 'white', position: 'relative',
                                display: 'flex', flexDirection: 'column', boxShadow: '-10px 0 30px rgba(0,0,0,0.1)'
                            }}
                        >
                            <div style={{ padding: '24px', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                                        {selectedTemplate.icon ? (
                                            <img src={selectedTemplate.icon} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="" />
                                        ) : (
                                            <Server size={20} color="#111827" />
                                        )}
                                    </div>
                                    <div>
                                        <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#111827', margin: 0 }}>{selectedTemplate.display_name || selectedTemplate.name}</h2>
                                        <div style={{ fontSize: '12px', color: '#6b7280' }}>MCP Server Setup</div>
                                    </div>
                                </div>
                                <button onClick={() => setSelectedTemplate(null)} style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#9ca3af' }}>
                                    <X size={20} />
                                </button>
                            </div>

                            <div style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
                                <div>
                                    <label style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px', display: 'block' }}>Description</label>
                                    <p style={{ fontSize: '14px', color: '#374151', margin: 0, lineHeight: '1.6' }}>{selectedTemplate.description}</p>
                                </div>

                                <div>
                                    <label style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px', display: 'block' }}>Configuration</label>
                                    <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '12px', fontFamily: 'monospace', color: '#475569' }}>
                                        <div style={{ marginBottom: '4px' }}><span style={{ color: '#94a3b8' }}>transport:</span> {selectedTemplate.transport}</div>
                                        {selectedTemplate.transport === 'stdio' ? (
                                            <>
                                                <div style={{ marginBottom: '4px' }}><span style={{ color: '#94a3b8' }}>command:</span> {selectedTemplate.command}</div>
                                                <div><span style={{ color: '#94a3b8' }}>args:</span> {JSON.stringify(selectedTemplate.args)}</div>
                                            </>
                                        ) : (
                                            <div><span style={{ color: '#94a3b8' }}>url:</span> {selectedTemplate.url}</div>
                                        )}
                                        {selectedTemplate.timeout && selectedTemplate.timeout !== 30 && (
                                            <div style={{ marginTop: '4px' }}><span style={{ color: '#94a3b8' }}>timeout:</span> {selectedTemplate.timeout}s</div>
                                        )}
                                    </div>
                                </div>

                                {selectedTemplate.required_env?.length > 0 && (
                                    <div>
                                        <label style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '12px', display: 'block' }}>Required Environment Variables</label>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                            {selectedTemplate.required_env.map(env => (
                                                <div key={env.key}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                                        <label style={{ fontSize: '13px', fontWeight: 600, color: '#374151' }}>{env.label || env.key}</label>
                                                        {env.secret && <Shield size={14} color="#f59e0b" />}
                                                    </div>
                                                    <input
                                                        type={env.secret ? 'password' : 'text'}
                                                        value={configEnv[env.key] || ''}
                                                        onChange={(e) => setConfigEnv({ ...configEnv, [env.key]: e.target.value })}
                                                        style={{
                                                            width: '100%', padding: '10px 12px', borderRadius: '8px', border: '1px solid #e5e7eb',
                                                            fontSize: '14px', outline: 'none'
                                                        }}
                                                        placeholder={`Enter ${env.key}...`}
                                                    />
                                                    {env.description && <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '4px' }}>{env.description}</div>}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div>
                                    <label style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px', display: 'block' }}>Target Agent</label>
                                    <Select
                                        options={agents.map(agent => ({ value: agent.uuid, label: agent.agent_name }))}
                                        value={targetAgent ? { value: targetAgent, label: agents.find(a => a.uuid === targetAgent)?.agent_name } : null}
                                        onChange={(opt) => setTargetAgent(opt?.value || '')}
                                        placeholder="Select an Agent..."
                                        styles={{
                                            control: (base) => ({ ...base, borderRadius: '10px', fontSize: '14px', border: '1px solid #e5e7eb', boxShadow: 'none', '&:hover': { borderColor: '#111827' } }),
                                            option: (base, state) => ({ ...base, fontSize: '14px', background: state.isSelected ? '#111827' : 'white', '&:hover': { background: '#f3f4f6', color: '#111827' } }),
                                        }}
                                    />
                                </div>

                                {testResult && (
                                    <div style={{
                                        padding: '12px', borderRadius: '8px',
                                        background: testResult.success ? '#f0fdf4' : '#fef2f2',
                                        border: `1px solid ${testResult.success ? '#bbf7d0' : '#fecaca'}`,
                                        display: 'flex', gap: '12px', alignItems: 'flex-start'
                                    }}>
                                        {testResult.success ? <Check size={18} color="#15803d" /> : <AlertCircle size={18} color="#b91c1c" />}
                                        <div>
                                            <div style={{ fontSize: '13px', fontWeight: 600, color: testResult.success ? '#15803d' : '#b91c1c' }}>
                                                {testResult.success ? `Connection Successful: ${testResult.tool_count} tools found` : 'Connection Failed'}
                                            </div>
                                            {!testResult.success && <div style={{ fontSize: '12px', color: '#b91c1c', marginTop: '2px' }}>{testResult.error}</div>}
                                            {testResult.success && (
                                                <div style={{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                                    {testResult.tools.slice(0, 5).map(t => (
                                                        <span key={t.name} style={{ fontSize: '10px', background: 'rgba(21, 128, 61, 0.1)', color: '#15803d', padding: '2px 6px', borderRadius: '4px' }}>{t.name}</span>
                                                    ))}
                                                    {testResult.tool_count > 5 && <span style={{ fontSize: '10px', color: '#15803d' }}>+{testResult.tool_count - 5} more</span>}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div style={{ padding: '24px', borderTop: '1px solid #e5e7eb', display: 'flex', flexDirection: 'column', gap: '16px', background: '#fcfcfc' }}>
                                {(!testResult?.success && !testing) && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 14px', background: '#fef3c7', borderRadius: '8px', border: '1px solid #fde68a' }}>
                                        <InfoIcon size={14} color="#92400e" />
                                        <div style={{ fontSize: '12px', color: '#92400e', fontWeight: 500 }}>
                                            Connect test required before adding to an agent.
                                        </div>
                                    </div>
                                )}
                                <div style={{ display: 'flex', gap: '12px' }}>
                                    <button
                                        onClick={handleTestConnection}
                                        disabled={testing}
                                        style={{
                                            flex: 1, height: '44px', borderRadius: '10px', background: 'white', color: '#111827',
                                            border: '1px solid #e5e7eb', fontSize: '14px', fontWeight: 700, cursor: 'pointer',
                                            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                                            transition: 'all 0.2s'
                                        }}
                                        onMouseOver={e => e.currentTarget.style.borderColor = '#111827'}
                                        onMouseOut={e => e.currentTarget.style.borderColor = '#e5e7eb'}
                                    >
                                        {testing ? <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1 }}><AlertCircle size={16} /></motion.div> : <Package size={16} />}
                                        {testing ? 'Testing...' : 'Test Connection'}
                                    </button>
                                    <button
                                        onClick={handleAddToAgent}
                                        disabled={submitting || !targetAgent || !testResult?.success}
                                        style={{
                                            flex: 1.5, height: '44px', borderRadius: '10px',
                                            background: submitting || !targetAgent || !testResult?.success ? '#e5e7eb' : '#111827',
                                            color: submitting || !targetAgent || !testResult?.success ? '#9ca3af' : 'white',
                                            border: 'none', fontSize: '14px', fontWeight: 700,
                                            cursor: submitting || !targetAgent || !testResult?.success ? 'not-allowed' : 'pointer',
                                            transition: 'all 0.2s',
                                            boxShadow: submitting || !targetAgent || !testResult?.success ? 'none' : '0 4px 12px rgba(17, 24, 39, 0.15)'
                                        }}
                                    >
                                        {submitting ? 'Adding...' : 'Add to Agent'}
                                    </button>
                                </div>
                            </div>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>

            {/* Create Template Modal (Simplified for now) */}
            {showCreateModal && (
                <div style={{ position: 'fixed', inset: 0, zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)' }}>
                    <div style={{ background: 'white', borderRadius: '20px', width: '100%', maxWidth: '600px', maxHeight: '90vh', overflow: 'hidden', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)' }}>
                        <div style={{ padding: '24px', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#111827', margin: 0 }}>Create MCP Template</h2>
                            <button onClick={() => setShowCreateModal(false)} style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#9ca3af' }}><X size={20} /></button>
                        </div>
                        <div style={{ padding: '24px', overflowY: 'auto' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                {/* Multi-step form or complex form would go here as per spec lines 46-55 */}
                                <div style={{ padding: '40px', textAlign: 'center', background: '#f8fafc', borderRadius: '12px', border: '1px dashed #e2e8f0' }}>
                                    <Code size={48} color="#94a3b8" style={{ marginBottom: '16px' }} />
                                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>Custom Server Editor</h3>
                                    <p style={{ fontSize: '14px', color: '#64748b', marginBottom: '24px' }}>Advanced template creation and JSON import are available here.</p>
                                    <textarea
                                        placeholder="Paste MCPServerSpec JSON here..."
                                        value={importJson}
                                        onChange={(e) => setImportJson(e.target.value)}
                                        style={{ width: '100%', height: '150px', padding: '12px', borderRadius: '8px', border: '1px solid #e5e7eb', fontFamily: 'monospace', fontSize: '12px' }}
                                    />
                                    <button
                                        style={{ marginTop: '16px', padding: '10px 20px', background: '#111827', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: 600 }}
                                        onClick={async () => {
                                            try {
                                                const spec = JSON.parse(importJson);
                                                const res = await fetch('/api/mcp/templates', {
                                                    method: 'POST',
                                                    headers: { 'Content-Type': 'application/json' },
                                                    body: JSON.stringify(spec)
                                                });
                                                if (res.ok) {
                                                    const newTpl = await res.json();
                                                    setTemplates([newTpl, ...templates]);
                                                    setShowCreateModal(false);
                                                } else {
                                                    const data = await res.json();
                                                    alert(data.error || "Failed to create template");
                                                }
                                            } catch (e) {
                                                alert("Invalid JSON: " + e.message);
                                            }
                                        }}
                                    >
                                        Create Template
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
