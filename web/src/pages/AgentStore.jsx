import { useState, useEffect } from 'react';
import { Plus, Save, Trash2, FileCode, Layout, Settings, ChevronRight, X, Check, User, MessageSquare, Users, UserPlus, Shield, Info, Terminal, Bot, Activity, Search, Share2, Book, Database, Filter, Eye, UserCheck, GitGraph } from 'lucide-react';
import Editor from '@monaco-editor/react';
import yaml from 'js-yaml';
import Select from 'react-select';
import CreatableSelect from 'react-select/creatable';
import { useNavigate, useSearchParams } from 'react-router-dom';
import LoadingView from '../components/LoadingView';
import EmptyState from '../components/EmptyState';

const Toggle = ({ checked, onChange, label }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }} onClick={() => onChange(!checked)}>
        {label && <span style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>{label}</span>}
        <div style={{
            width: '32px', height: '18px', background: checked ? '#10b981' : '#cbd5e1',
            borderRadius: '10px', position: 'relative', transition: 'all 0.2s ease-in-out'
        }}>
            <div style={{
                width: '14px', height: '14px', background: 'white', borderRadius: '50%',
                position: 'absolute', top: '2px', left: checked ? '16px' : '2px',
                transition: 'all 0.2s ease-in-out', boxShadow: '0 1px 2px rgba(0,0,0,0.1)'
            }} />
        </div>
    </div>
);

const HitlChannelCard = ({ channel, onUpdate, onDelete, availableRefs = [] }) => {
    const [yamlText, setYamlText] = useState('');

    useEffect(() => {
        const extras = { ...channel };
        delete extras.ref;
        delete extras.type;
        setYamlText(Object.keys(extras).length > 0 ? yaml.dump(extras) : '');
    }, [channel.ref]);

    const handleYamlChange = (val) => {
        setYamlText(val);
        try {
            const parsed = yaml.load(val) || {};
            // Preserve ref and type, update everything else from parsed object
            onUpdate({ ref: channel.ref, type: channel.type, ...parsed });
        } catch (e) {
            // Keep typing
        }
    };

    const isRefSelected = channel.ref && availableRefs.includes(channel.ref);

    return (
        <div style={{ padding: '16px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '10px', position: 'relative' }}>
            <button
                onClick={onDelete}
                style={{ position: 'absolute', top: '12px', right: '12px', border: 'none', background: 'none', color: '#94a3b8', padding: '4px', cursor: 'pointer', transition: 'color 0.2s' }}
                onMouseOver={e => e.currentTarget.style.color = '#ef4444'}
                onMouseOut={e => e.currentTarget.style.color = '#94a3b8'}
            >
                <X size={16} />
            </button>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '10px', fontWeight: 700, color: '#94a3b8' }}>CHANNEL NAME / REF</label>
                    <CreatableSelect
                        options={availableRefs.map(r => ({ value: r, label: r }))}
                        value={channel.ref ? { label: channel.ref, value: channel.ref } : null}
                        onChange={val => onUpdate({ ...channel, ref: val ? val.value : '' })}
                        placeholder="e.g. lark-main"
                        styles={{
                            control: (base) => ({ ...base, minHeight: '32px', height: '32px', fontSize: '12px', borderColor: '#e5e7eb', borderRadius: '4px' }),
                            valueContainer: (base) => ({ ...base, padding: '0 8px' }),
                            input: (base) => ({ ...base, margin: 0, padding: 0 }),
                            indicatorsContainer: (base) => ({ ...base, height: '30px' })
                        }}
                    />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '10px', fontWeight: 700, color: '#94a3b8' }}>CHANNEL TYPE</label>
                    <select
                        className="input-field"
                        style={{ height: '32px', fontSize: '12px' }}
                        value={channel.type || 'lark'}
                        onChange={e => onUpdate({ ...channel, type: e.target.value })}
                    >
                        <option value="lark">Lark (Webhook)</option>
                        <option value="lark_ws">Lark (WS)</option>
                    </select>
                </div>
            </div>
            <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '10px', fontWeight: 700, color: '#94a3b8' }}>EXTRA CONFIG (YAML){isRefSelected ? ' - Optional' : ''}</label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'stretch' }}>
                    <textarea
                        className="input-field"
                        style={{ flex: 1, minHeight: '120px', fontFamily: 'monospace', fontSize: '12px', background: '#fff', padding: '8px 12px', resize: 'vertical' }}
                        value={yamlText}
                        onChange={e => handleYamlChange(e.target.value)}
                        placeholder={
                            (channel.type || 'lark') === 'lark_ws'
                                ? 'app_id: "..."\napp_secret: "..."\nchat_id: "..."\nbot_name: "..."\ndomain: "feishu"'
                                : 'app_id: "..."\napp_secret: "..."\nverification_token: "..."\nchat_id: "..."\nbot_name: "..."\ndomain: "feishu"'
                        }
                    />
                    <div style={{ width: '160px', background: '#f1f5f9', padding: '8px 10px', borderRadius: '6px', fontSize: '10px', color: '#64748b', fontFamily: 'monospace', border: '1px solid #e2e8f0', overflow: 'hidden' }}>
                        <div style={{ color: '#94a3b8', marginBottom: '6px', fontWeight: 600, fontFamily: 'Inter' }}>Available Keys</div>
                        <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>
                            {channel.type === 'lark_ws'
                                ? 'app_id: ""\napp_secret: ""\nchat_id: ""\nbot_name: ""\ndomain: "feishu"'
                                : 'app_id: ""\napp_secret: ""\nverification_token: ""\nchat_id: ""\nbot_name: ""\ndomain: "feishu"'}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

const SubAgentCard = ({ name, spec, agents, allSkills, allTools, onUpdate, onDelete }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const hasOverrides = (spec.instructions && spec.instructions.length > 0) ||
        (spec.tools && spec.tools.length > 0) ||
        (spec.skills && spec.skills.length > 0) ||
        (spec.adviced_model_kind && spec.adviced_model_kind !== 'inherit');

    return (
        <div style={{ padding: '10px 12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 700, color: '#1e293b' }}>{name}</span>
                    <span style={{ fontSize: '9px', color: '#94a3b8', background: '#f1f5f9', padding: '1px 4px', borderRadius: '4px', textTransform: 'uppercase' }}>ID</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <button
                        onClick={() => setIsExpanded(!isExpanded)}
                        style={{ fontSize: '10px', color: '#3b82f6', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '2px' }}>
                        {isExpanded ? 'Hide' : 'Configure'} {(hasOverrides && !isExpanded) && <div style={{ width: '4px', height: '4px', background: '#10b981', borderRadius: '50%' }} />}
                    </button>
                    <button onClick={onDelete} style={{ color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', padding: '2px' }}>
                        <X size={14} />
                    </button>
                </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 90px 50px', gap: '8px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>LINKED AGENT</label>
                    <select
                        className="input-field"
                        style={{ height: '28px', fontSize: '11px', padding: '0 8px' }}
                        value={spec.ref_uuid || ''}
                        onChange={e => onUpdate('ref_uuid', e.target.value || null)}
                    >
                        <option value="">-- Ad-hoc --</option>
                        {agents.map(a => <option key={a.uuid} value={a.uuid}>{a.agent_name}</option>)}
                    </select>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>DESCRIPTION / ROLE</label>
                    <input
                        className="input-field"
                        style={{ height: '28px', fontSize: '11px', padding: '0 8px' }}
                        placeholder="Role..."
                        value={spec.description || ''}
                        onChange={e => onUpdate('description', e.target.value)}
                    />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>MODEL</label>
                    <select
                        className="input-field"
                        style={{ height: '28px', fontSize: '11px', padding: '0 4px' }}
                        value={spec.adviced_model_kind || 'inherit'}
                        onChange={e => onUpdate('adviced_model_kind', e.target.value)}
                    >
                        <option value="inherit">Inherit</option>
                        <option value="smart">Smart</option>
                        <option value="fast">Fast</option>
                        <option value="reasoning">Reasoning</option>
                    </select>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>TURNS</label>
                    <input
                        type="number"
                        className="input-field"
                        style={{ height: '28px', fontSize: '11px', padding: '0 8px' }}
                        value={spec.max_turns ?? 20}
                        onChange={e => onUpdate('max_turns', parseInt(e.target.value))}
                    />
                </div>
            </div>

            {
                isExpanded && (
                    <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px dashed #e2e8f0', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <label style={{ fontSize: '9px', fontWeight: 600, color: '#64748b' }}>SPECIFIC INSTRUCTIONS</label>
                            <textarea
                                className="input-field"
                                style={{ height: '60px', fontSize: '11px', resize: 'vertical', fontFamily: 'monospace', padding: '8px' }}
                                placeholder="Optional override..."
                                value={spec.instructions || ''}
                                onChange={e => onUpdate('instructions', e.target.value)}
                            />
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <label style={{ fontSize: '9px', fontWeight: 600, color: '#64748b' }}>OVERRIDE SKILLS</label>
                            <Select
                                isMulti
                                options={allSkills}
                                value={(spec.skills || []).map(s => ({ value: s, label: s }))}
                                onChange={(val) => onUpdate('skills', val ? val.map(v => v.value) : [])}
                                styles={{
                                    control: (base) => ({ ...base, borderColor: '#e5e7eb', borderRadius: '4px', fontSize: '11px', minHeight: '28px' }),
                                    menu: (base) => ({ ...base, fontSize: '11px' }),
                                    multiValue: (base) => ({ ...base, fontSize: '10px' })
                                }}
                                placeholder="Skills..."
                            />
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <label style={{ fontSize: '9px', fontWeight: 600, color: '#64748b' }}>OVERRIDE TOOLS</label>
                            <Select
                                isMulti
                                options={allTools}
                                value={(spec.tools || []).map(t => ({ value: t, label: t }))}
                                onChange={(val) => onUpdate('tools', val ? val.map(v => v.value) : [])}
                                styles={{
                                    control: (base) => ({ ...base, borderColor: '#e5e7eb', borderRadius: '4px', fontSize: '11px', minHeight: '28px' }),
                                    menu: (base) => ({ ...base, fontSize: '11px' }),
                                    multiValue: (base) => ({ ...base, fontSize: '10px' })
                                }}
                                placeholder="Tools..."
                            />
                        </div>
                    </div>
                )
            }
        </div>
    );
};

const TagList = ({ items, onRemove }) => {
    if (!items || items.length === 0) return null;
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
            {items.map(item => (
                <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#eff6ff', border: '1px solid #dbeafe', color: '#1e40af', padding: '4px 10px', borderRadius: '16px', fontSize: '12px', fontWeight: 500 }}>
                    {item}
                    <X size={12} style={{ cursor: 'pointer' }} onClick={() => onRemove(item)} />
                </div>
            ))}
        </div>
    );
};

const SelectedList = ({ items, onRemove, allItems }) => {
    if (!items || items.length === 0) return null;
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
            {items.map(itemName => {
                const details = allItems.find(i => i.value === itemName);
                return (
                    <div key={itemName} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                            <div style={{ fontWeight: 600, fontSize: '13px', color: '#1e293b' }}>{itemName}</div>
                            {details?.description && <div style={{ fontSize: '11px', color: '#64748b' }}>{details.description}</div>}
                        </div>
                        <X size={14} color="#94a3b8" style={{ cursor: 'pointer' }} onClick={() => onRemove(itemName)} />
                    </div>
                );
            })}
        </div>
    );
};

const SaveModal = ({ isOpen, result, onClose }) => {
    if (!isOpen) return null;
    const isSuccess = result.status === 'success';
    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
            <div style={{ background: 'white', padding: '32px', borderRadius: '12px', maxWidth: '500px', width: '90%', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)', textAlign: 'center' }}>
                <div style={{ padding: '12px', borderRadius: '50%', background: isSuccess ? '#ecfdf5' : '#fef2f2', width: 'fit-content', margin: '0 auto 16px' }}>
                    {isSuccess ? <Check size={32} color="#10b981" /> : <X size={32} color="#ef4444" />}
                </div>
                <h3 style={{ margin: '0 0 8px 0', fontSize: '18px', fontWeight: 700, color: '#111827' }}>{isSuccess ? 'Saved Successfully' : 'Save Failed'}</h3>
                <p style={{ margin: '0 0 16px 0', fontSize: '14px', color: '#6b7280' }}>{result.message}</p>

                {!isSuccess && result.debug && (
                    <div style={{ textAlign: 'left', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '12px', marginBottom: '24px', maxHeight: '200px', overflow: 'auto' }}>
                        <div style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: '8px' }}>Debug Information</div>
                        <pre style={{ margin: 0, fontSize: '11px', color: '#1e293b', whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace' }}>
                            {typeof result.debug === 'string' ? result.debug : JSON.stringify(result.debug, null, 2)}
                        </pre>
                    </div>
                )}

                <button
                    className={`btn ${isSuccess ? 'btn-primary' : ''}`}
                    style={{ width: '100%', justifyContent: 'center', background: !isSuccess ? '#111827' : '', color: 'white' }}
                    onClick={onClose}
                >
                    Close
                </button>
            </div>
        </div>
    );
};

const DeleteModal = ({ isOpen, agent, onConfirm, onClose }) => {
    if (!isOpen) return null;
    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(4px)' }}>
            <div style={{ background: 'white', padding: '32px', borderRadius: '16px', maxWidth: '400px', width: '90%', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', border: '1px solid #e5e7eb' }}>
                <div style={{ padding: '12px', borderRadius: '50%', background: '#fef2f2', width: 'fit-content', margin: '0 auto 16px' }}>
                    <Trash2 size={32} color="#ef4444" />
                </div>
                <h3 style={{ margin: '0 0 8px 0', fontSize: '20px', fontWeight: 800, color: '#111827', textAlign: 'center' }}>Delete Agent?</h3>
                <p style={{ margin: '0 0 24px 0', fontSize: '14px', color: '#6b7280', textAlign: 'center' }}>
                    Are you sure you want to delete <strong>{agent?.agent_name}</strong>? This action cannot be undone.
                </p>
                <div style={{ display: 'flex', gap: '12px' }}>
                    <button className="btn" style={{ flex: 1, justifyContent: 'center', fontWeight: 600 }} onClick={onClose}>Cancel</button>
                    <button className="btn btn-primary" style={{ flex: 1, justifyContent: 'center', background: '#ef4444', border: 'none', fontWeight: 600 }} onClick={onConfirm}>Delete</button>
                </div>
            </div>
        </div>
    );
};
const TabButton = ({ id, label, active, onClick, icon }) => (
    <button
        onClick={onClick}
        style={{
            flex: 1,
            padding: '8px 0',
            fontSize: '11px',
            fontWeight: 600,
            textTransform: 'uppercase',
            border: 'none',
            background: 'transparent',
            color: active ? '#111827' : '#94a3b8',
            borderBottom: active ? '2px solid #111827' : '2px solid transparent',
            cursor: 'pointer',
            transition: 'all 0.2s',
            letterSpacing: '0.05em',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
        }}
    >
        {icon}
        {label}
    </button>
);

const SubTabButton = ({ id, label, icon: Icon, active, enabled, onClick }) => (
    <button
        onClick={onClick}
        style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '10px',
            padding: '10px 16px',
            fontSize: '13px',
            fontWeight: active ? 600 : 500,
            color: active ? '#111827' : '#64748b',
            background: active ? '#f3f4f6' : 'transparent',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            textAlign: 'left',
            transition: 'all 0.2s',
            position: 'relative'
        }}
        onMouseOver={e => !active && (e.currentTarget.style.background = '#f9fafb')}
        onMouseOut={e => !active && (e.currentTarget.style.background = 'transparent')}
    >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Icon size={16} />
            {label}
        </div>
        {enabled !== undefined && (
            <div style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: enabled ? '#10b981' : '#e2e8f0',
                boxShadow: enabled ? '0 0 8px #10b981aa' : 'none'
            }} />
        )}
    </button>
);

export default function AgentStore() {
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const [agents, setAgents] = useState([]);
    const [selectedAgent, setSelectedAgent] = useState(null);
    const [loading, setLoading] = useState(true);
    const [editMode, setEditMode] = useState('form'); // 'yaml' or 'form'
    const [editorContent, setEditorContent] = useState('');
    const [saveModal, setSaveModal] = useState({ isOpen: false, result: { status: '', message: '' } });
    const [deleteModal, setDeleteModal] = useState({ isOpen: false, agent: null });
    const [sourceTab, setSourceTab] = useState('builtin');
    const [addSubAgentModal, setAddSubAgentModal] = useState({ isOpen: false });

    const [activeSubTab, setActiveSubTab] = useState('basic');
    const [agentSessions, setAgentSessions] = useState([]);
    const [agentLoops, setAgentLoops] = useState([]);

    const [allSkills, setAllSkills] = useState([]);
    const [allTools, setAllTools] = useState([]);
    const [globalHitlChannels, setGlobalHitlChannels] = useState([]);

    const handleStartChat = () => {
        if (!selectedAgent) return;
        navigate(`/sessions?agent_uuid=${encodeURIComponent(selectedAgent.uuid)}`);
    };

    const startChat = (agent) => {
        const agentUuid = agent.uuid || '';
        if (!agentUuid) return;
        navigate(`/sessions?agent_uuid=${encodeURIComponent(agentUuid)}`);
    };

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [agentsRes, skillsRes, toolsRes, configRes] = await Promise.all([
                    fetch('/api/agents'),
                    fetch('/api/skills'),
                    fetch('/api/tools'),
                    fetch('/api/config')
                ]);

                const agentsData = await agentsRes.json();
                const skillsData = await skillsRes.json();
                const toolsData = await toolsRes.json();
                const configData = await configRes.json();

                setAgents(agentsData);
                setAllSkills(skillsData.map(s => ({ value: s.name, label: s.name, description: s.description })));
                setAllTools(toolsData.map(t => ({ value: t.name, label: t.name, description: t.description })));
                if (configData.hitl_channels) {
                    setGlobalHitlChannels(configData.hitl_channels.map(c => c.ref).filter(Boolean));
                }
                setLoading(false);
            } catch (err) {
                console.error("Fetch error:", err);
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    // Sync state with URL params
    useEffect(() => {
        if (loading || agents.length === 0) return;

        const uuidParam = searchParams.get('uuid');
        const tabParam = searchParams.get('tab');
        const subParam = searchParams.get('sub');

        let currentTab = sourceTab;

        if (subParam && subParam !== activeSubTab) setActiveSubTab(subParam);
        if (tabParam && tabParam !== sourceTab) {
            setSourceTab(tabParam);
            currentTab = tabParam;
        }

        let agentToSelect = null;

        if (uuidParam && uuidParam !== 'undefined') {
            agentToSelect = agents.find(a => a.uuid === uuidParam) || agents.find(a => a.agent_name === uuidParam);
        }

        // Fallback: If no valid agent was found from UUID (or no UUID at all), auto-select first available
        if (!agentToSelect) {
            const currentTabAgents = agents.filter(a => (a.source || 'custom') === currentTab);
            if (currentTabAgents.length > 0) {
                agentToSelect = currentTabAgents[0];
            } else if (agents.length > 0 && !tabParam) {
                // Only fallback to another tab on initial load, not when user explicitly selected a tab
                agentToSelect = agents[0];
                currentTab = agentToSelect.source || 'custom';
                setSourceTab(currentTab);
            }
        }

        if (agentToSelect) {
            const agentSource = agentToSelect.source || 'custom';
            // Align local tab state if we jumped to a different source implicitly
            if (currentTab !== agentSource && !tabParam) setSourceTab(agentSource);

            const selectedId = selectedAgent?.uuid || selectedAgent?.agent_name;
            const targetId = agentToSelect.uuid || agentToSelect.agent_name;
            if (selectedId !== targetId) {
                setSelectedAgent(agentToSelect);
                setEditorContent(yaml.dump(agentToSelect));
            }

            // Always ensure the URL reflects the currently focused agent
            const agentId = agentToSelect.uuid || agentToSelect.agent_name;
            if (uuidParam !== agentId || tabParam !== agentSource) {
                updateUrlParams({ uuid: agentId, tab: agentSource }, { replace: !uuidParam || uuidParam === 'undefined' });
            }
        }
    }, [loading, agents, searchParams]);

    useEffect(() => {
        if (!selectedAgent || !selectedAgent.agent_name) return;

        // Clear previous data while loading new
        if (activeSubTab === 'sessions') setAgentSessions([]);
        if (activeSubTab === 'loops') setAgentLoops([]);

        if (activeSubTab === 'sessions') {
            fetch(`/api/sessions?agent_uuid=${encodeURIComponent(selectedAgent.uuid)}`)
                .then(res => res.json())
                .then(data => setAgentSessions(Array.isArray(data) ? data : []))
                .catch(err => {
                    console.error("Fetch sessions error:", err);
                    setAgentSessions([]);
                });
        } else if (activeSubTab === 'loops') {
            fetch('/api/daemon/loops')
                .then(res => res.json())
                .then(data => {
                    const loops = Object.entries(data.loops || {})
                        .filter(([name]) => name === selectedAgent.agent_name)
                        .map(([name, status]) => ({ name, ...status }));
                    setAgentLoops(loops);
                })
                .catch(err => {
                    console.error("Fetch loops error:", err);
                    setAgentLoops([]);
                });
        }
    }, [activeSubTab, selectedAgent?.agent_name, selectedAgent?.uuid]);

    const updateUrlParams = (params, options = { replace: true }) => {
        const newParams = new URLSearchParams(searchParams);
        Object.entries(params).forEach(([key, value]) => {
            if (value === null) newParams.delete(key);
            else newParams.set(key, value);
        });
        setSearchParams(newParams, options);
    };

    const selectAgent = (agent, updateUrl = true) => {
        if (!agent) return;
        setSelectedAgent(agent);
        setEditorContent(yaml.dump(agent));
        const newSource = agent.source || 'custom';
        if (updateUrl && agent.uuid) {
            updateUrlParams({ uuid: agent.uuid, tab: newSource });
        }
    };

    const handleSourceTabChange = (tab) => {
        setSourceTab(tab);
        updateUrlParams({ tab, uuid: null, sub: 'basic' });
        // Auto select first agent in new tab if available
        const firstInTab = agents.find(a => (a.source || 'custom') === tab);
        if (firstInTab) {
            selectAgent(firstInTab);
        } else {
            setSelectedAgent(null);
        }
    };

    const handleSubTabChange = (sub) => {
        setActiveSubTab(sub);
        updateUrlParams({ sub });
    };

    const handleCreate = () => {
        navigate('/sessions?agent_uuid=builtin_agent_creator');
    };

    const handleSave = () => {
        let spec;
        try {
            spec = editMode === 'yaml' ? yaml.load(editorContent) : selectedAgent;
            if (!spec.agent_name) {
                setSaveModal({ isOpen: true, result: { status: 'error', message: 'Agent Name is required' } });
                return;
            }

            const isNew = !agents.some(a => a.agent_name === spec.agent_name);
            const url = isNew ? '/api/agents' : `/api/agents/${spec.agent_name}`;
            const method = isNew ? 'POST' : 'PUT';

            fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(spec)
            }).then(async res => {
                const data = await res.json();
                if (res.ok) {
                    const updatedSpec = { ...spec };
                    setSaveModal({ isOpen: true, result: { status: 'success', message: `Agent '${spec.agent_name}' has been saved successfully.` } });
                    // Refresh current agent in list
                    const newAgents = isNew ? [updatedSpec, ...agents.filter(a => a !== selectedAgent)] : agents.map(a => a.agent_name === spec.agent_name ? updatedSpec : a);
                    setAgents(newAgents);
                    setSelectedAgent(updatedSpec);
                } else {
                    setSaveModal({
                        isOpen: true,
                        result: {
                            status: 'error',
                            message: 'Failed to save agent.',
                            debug: data.detail || data
                        }
                    });
                }
            }).catch(err => {
                setSaveModal({ isOpen: true, result: { status: 'error', message: 'Network error or server unavailable', debug: err.message } });
            });
        } catch (e) {
            setSaveModal({ isOpen: true, result: { status: 'error', message: 'Invalid YAML/JSON', debug: e.message } });
        }
    };

    const handleDelete = async () => {
        if (!selectedAgent) return;

        // If it's a new unsaved agent (no uuid), just remove from list
        if (!selectedAgent.uuid) {
            const updatedAgents = agents.filter(a => a !== selectedAgent);
            setAgents(updatedAgents);
            if (updatedAgents.length > 0) selectAgent(updatedAgents[0]);
            else setSelectedAgent(null);
            setDeleteModal({ isOpen: false, agent: null });
            return;
        }

        // For saved agents, call the API
        try {
            const res = await fetch(`/api/agents/${selectedAgent.agent_name}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                const updatedAgents = agents.filter(a => a.uuid !== selectedAgent.uuid);
                setAgents(updatedAgents);
                if (updatedAgents.length > 0) selectAgent(updatedAgents[0]);
                else setSelectedAgent(null);
            } else {
                const data = await res.json();
                alert(data.detail || "Failed to delete agent");
            }
        } catch (err) {
            console.error("Delete error:", err);
            alert("Delete failed due to network error");
        }
        setDeleteModal({ isOpen: false, agent: null });
    };



    const updateField = (field, value) => {
        const updated = { ...selectedAgent, [field]: value };
        setSelectedAgent(updated);
        if (editMode === 'yaml') {
            setEditorContent(yaml.dump(updated));
        }
    };

    const updateSubAgentField = (name, field, value) => {
        const sub_agents = { ...selectedAgent.sub_agents };
        sub_agents[name] = { ...sub_agents[name], [field]: value };
        updateField('sub_agents', sub_agents);
    };

    const filteredAgents = agents.filter(a => (a.source || 'custom') === sourceTab);

    if (loading) return <LoadingView message="Loading Agents..." />;

    return (
        <div className="split-view" style={{ flex: 1, height: '100vh', overflow: 'hidden' }}>
            {/* Left Panel: List */}
            <div className="left-panel" style={{ background: '#fcfcfc', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
                <div style={{ height: '60px', padding: '0 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'white', flexShrink: 0 }}>
                    <h2 style={{ fontSize: '15px', color: '#111827', fontWeight: 700, margin: 0 }}>Agents</h2>
                    {sourceTab !== 'builtin' && (
                        <button
                            className="btn"
                            style={{ padding: '4px 8px' }}
                            onClick={handleCreate}
                            title="Add Agent"
                        >
                            <Plus size={16} />
                        </button>
                    )}
                </div>

                {/* Source Tabs */}
                <div style={{ display: 'flex', borderBottom: '1px solid #e5e7eb', marginBottom: '8px' }}>
                    <TabButton label="Built-in" active={sourceTab === 'builtin'} onClick={() => handleSourceTabChange('builtin')} />
                    <TabButton label="Customize" active={sourceTab === 'custom'} onClick={() => handleSourceTabChange('custom')} />
                </div>

                <div style={{ flex: 1, overflowY: 'auto', padding: '12px 0' }}>
                    {filteredAgents.length === 0 ? (
                        <div style={{ padding: '40px 24px', textAlign: 'center', color: '#94a3b8', fontSize: '13px' }}>
                            {sourceTab === 'custom' ? (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                                    <div style={{ color: '#cbd5e1' }}><Bot size={28} /></div>
                                    <div>No custom agents yet</div>
                                    <button
                                        className="btn"
                                        style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 14px', fontSize: '12px', fontWeight: 600 }}
                                        onClick={handleCreate}
                                    >
                                        <Plus size={14} /> Create
                                    </button>
                                </div>
                            ) : (
                                'No agents found in this category.'
                            )}
                        </div>
                    ) : (
                        filteredAgents.map(agent => (
                            <div
                                key={agent.uuid}
                                className={`list-item ${selectedAgent?.uuid === agent.uuid ? 'active' : ''}`}
                                onClick={() => selectAgent(agent)}
                                style={{
                                    borderLeft: selectedAgent?.uuid === agent.uuid ? '3px solid #111827' : '3px solid transparent',
                                    display: 'flex',
                                    alignItems: 'flex-start',
                                    gap: '12px',
                                    padding: '12px 24px'
                                }}
                            >
                                <div style={{
                                    width: '32px',
                                    height: '32px',
                                    borderRadius: '8px',
                                    background: (agent.source || 'custom') === 'builtin' ? '#f1f5f9' : '#f0f9ff',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    color: (agent.source || 'custom') === 'builtin' ? '#64748b' : '#0284c7',
                                    flexShrink: 0
                                }}>
                                    <User size={18} />
                                </div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 600, fontSize: '13.5px', marginBottom: '2px', color: '#111827' }}>{agent.agent_name}</div>
                                    <div className="text-xs text-gray" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '11px' }}>
                                        {agent.description || 'No description'}
                                    </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                                    <button
                                        style={{
                                            display: 'flex', alignItems: 'center', gap: '6px',
                                            padding: '0 14px', height: '32px', fontSize: '12px', fontWeight: 600,
                                            background: '#eff6ff', color: '#3b82f6', border: 'none',
                                            borderRadius: '6px', cursor: 'pointer',
                                            transition: 'all 0.2s'
                                        }}
                                        onClick={(e) => { e.stopPropagation(); startChat(agent); }}
                                    >
                                        <MessageSquare size={13} /> Chat
                                    </button>
                                    <div style={{ width: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                        {selectedAgent?.uuid === agent.uuid && <ChevronRight size={14} color="#111827" />}
                                    </div>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Right Panel: Editor Area */}
            <div className="right-panel" style={{ display: 'flex', flexDirection: 'column' }}>
                {selectedAgent ? (
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                        <div className="header" style={{ height: '60px', flexShrink: 0, background: 'white', borderBottom: '1px solid var(--border)', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <h3 style={{ fontSize: '15px', color: '#111827', fontWeight: 700, margin: 0 }}>{selectedAgent.agent_name}</h3>
                                <span style={{ fontSize: '10px', background: '#f1f5f9', color: '#64748b', padding: '1px 6px', borderRadius: '4px', fontWeight: 600 }}>V{selectedAgent.version}</span>
                            </div>
                            <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                                <div style={{ display: 'flex', background: '#f3f4f6', padding: '2px', borderRadius: '8px', border: '1px solid var(--border)', gap: '2px' }}>
                                    <button
                                        onClick={() => setEditMode('form')}
                                        className="mode-btn"
                                        style={{
                                            padding: '6px 14px',
                                            border: 'none',
                                            borderRadius: '6px',
                                            fontSize: '13px',
                                            fontWeight: 600,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '8px',
                                            background: editMode === 'form' ? 'white' : 'transparent',
                                            boxShadow: editMode === 'form' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                                            color: editMode === 'form' ? '#111827' : '#6b7280',
                                            transition: 'all 0.2s'
                                        }}
                                    >
                                        <Layout size={14} />
                                        Form
                                    </button>
                                    <button
                                        onClick={() => setEditMode('yaml')}
                                        className="mode-btn"
                                        style={{
                                            padding: '6px 14px',
                                            border: 'none',
                                            borderRadius: '6px',
                                            fontSize: '13px',
                                            fontWeight: 600,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '8px',
                                            background: editMode === 'yaml' ? 'white' : 'transparent',
                                            boxShadow: editMode === 'yaml' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                                            color: editMode === 'yaml' ? '#111827' : '#6b7280',
                                            transition: 'all 0.2s'
                                        }}
                                    >
                                        <FileCode size={14} />
                                        YAML
                                    </button>
                                </div>
                                <div style={{ width: '1px', height: '24px', background: '#e5e7eb', margin: '0 4px' }} />
                                <button className="btn" onClick={() => setDeleteModal({ isOpen: true, agent: selectedAgent })} style={{ height: '36px', color: '#ef4444', border: 'none', background: 'none' }} title="Delete Agent">
                                    <Trash2 size={18} />
                                </button>
                                <button className="btn btn-primary" onClick={handleSave} style={{ gap: '8px', padding: '0 16px', height: '36px', borderRadius: '8px', fontSize: '13px', fontWeight: 600 }}>
                                    <Save size={16} /> Save
                                </button>
                            </div>
                        </div>

                        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', background: 'white' }}>
                            {editMode === 'yaml' ? (
                                <div style={{ flex: 1, background: 'white' }}>
                                    <Editor
                                        height="100%"
                                        defaultLanguage="yaml"
                                        theme="light"
                                        value={editorContent}
                                        onChange={(val) => {
                                            setEditorContent(val);
                                            try {
                                                const parsed = yaml.load(val);
                                                if (parsed && typeof parsed === 'object') {
                                                    setSelectedAgent(parsed);
                                                }
                                            } catch (e) { }
                                        }}
                                        options={{
                                            minimap: { enabled: false },
                                            fontSize: 13,
                                            padding: { top: 16 },
                                            automaticLayout: true,
                                            scrollBeyondLastLine: false,
                                            lineNumbers: 'on',
                                            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
                                            renderLineHighlight: 'all'
                                        }}
                                    />
                                </div>
                            ) : (
                                <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                                    {/* Sub-Sidebar */}
                                    <div style={{ width: '220px', borderRight: '1px solid #e5e7eb', background: '#fcfcfc', padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                        <div style={{ fontSize: '10px', fontWeight: 700, color: '#94a3b8', padding: '8px 16px', letterSpacing: '0.05em' }}>SETTINGS</div>
                                        <SubTabButton id="basic" label="Basic" icon={Settings} active={activeSubTab === 'basic'} onClick={() => handleSubTabChange('basic')} />
                                        <SubTabButton id="instructions" label="Instructions" icon={Info} active={activeSubTab === 'instructions'} onClick={() => handleSubTabChange('instructions')} />

                                        <div style={{ height: '12px' }} />
                                        <div style={{ fontSize: '10px', fontWeight: 700, color: '#94a3b8', padding: '8px 16px', letterSpacing: '0.05em' }}>CAPABILITIES</div>
                                        <SubTabButton
                                            id="tools" label="Tools & Skills" icon={Terminal}
                                            active={activeSubTab === 'tools'}
                                            enabled={(selectedAgent.tools?.length > 0 || selectedAgent.skills?.length > 0)}
                                            onClick={() => handleSubTabChange('tools')}
                                        />
                                        <SubTabButton
                                            id="sub_agents" label="Sub-agents" icon={Users}
                                            active={activeSubTab === 'sub_agents'}
                                            enabled={Object.keys(selectedAgent.sub_agents || {}).length > 0}
                                            onClick={() => handleSubTabChange('sub_agents')}
                                        />
                                        <SubTabButton
                                            id="mcp" label="MCP" icon={Share2}
                                            active={activeSubTab === 'mcp'}
                                            enabled={selectedAgent.mcp_servers?.length > 0}
                                            onClick={() => handleSubTabChange('mcp')}
                                        />
                                        <SubTabButton
                                            id="knowledge" label="Knowledge" icon={Book}
                                            active={activeSubTab === 'knowledge'}
                                            enabled={selectedAgent.knowledge_base?.length > 0}
                                            onClick={() => handleSubTabChange('knowledge')}
                                        />
                                        <SubTabButton
                                            id="hitl" label="HITL (Human)" icon={UserCheck}
                                            active={activeSubTab === 'hitl'}
                                            enabled={selectedAgent.hitl_mode !== 'never'}
                                            onClick={() => handleSubTabChange('hitl')}
                                        />
                                        <SubTabButton
                                            id="workflow" label="Workflow (DAG)" icon={GitGraph}
                                            active={activeSubTab === 'workflow'}
                                            enabled={!!selectedAgent.workflow?.enable}
                                            onClick={() => handleSubTabChange('workflow')}
                                        />
                                        <SubTabButton
                                            id="daemon" label="Daemon (Claw)" icon={Bot}
                                            active={activeSubTab === 'daemon'}
                                            enabled={!!selectedAgent.autonomy?.enabled}
                                            onClick={() => handleSubTabChange('daemon')}
                                        />

                                        <div style={{ height: '12px' }} />
                                        <div style={{ fontSize: '10px', fontWeight: 700, color: '#94a3b8', padding: '8px 16px', letterSpacing: '0.05em' }}>RUNTIME</div>
                                        <SubTabButton id="sessions" label="Sessions" icon={MessageSquare} active={activeSubTab === 'sessions'} onClick={() => handleSubTabChange('sessions')} />
                                        <SubTabButton id="loops" label="Loops" icon={Activity} active={activeSubTab === 'loops'} onClick={() => handleSubTabChange('loops')} />
                                        <SubTabButton id="memory" label="Memory" icon={Database} active={activeSubTab === 'memory'} onClick={() => handleSubTabChange('memory')} />
                                        <div style={{ flex: 1 }} />
                                        <button
                                            onClick={() => navigate(`/tracing?agent_name=${encodeURIComponent(selectedAgent.agent_name)}`)}
                                            style={{
                                                width: '100%',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '10px',
                                                padding: '10px 16px',
                                                fontSize: '13px',
                                                fontWeight: 500,
                                                color: '#64748b',
                                                background: 'transparent',
                                                border: 'none',
                                                borderRadius: '6px',
                                                cursor: 'pointer',
                                                textAlign: 'left',
                                                transition: 'all 0.2s'
                                            }}
                                            onMouseOver={e => e.currentTarget.style.background = '#f3f4f6'}
                                            onMouseOut={e => e.currentTarget.style.background = 'transparent'}
                                        >
                                            <Eye size={16} />
                                            AUDIT
                                        </button>
                                    </div>

                                    {/* Tab Content */}
                                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto', background: '#f9fafb' }}>
                                        <div key={activeSubTab} style={{ padding: '24px', maxWidth: '1000px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column' }}>
                                            {activeSubTab === 'basic' && (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>AGENT INFORMATION</h4>
                                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>AGENT NAME</label>
                                                                <input className="input-field" value={selectedAgent.agent_name || ''} onChange={e => updateField('agent_name', e.target.value)} />
                                                            </div>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>VERSION</label>
                                                                <input className="input-field" value={selectedAgent.version || ''} onChange={e => updateField('version', e.target.value)} />
                                                            </div>
                                                        </div>
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '16px' }}>
                                                            <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>DESCRIPTION</label>
                                                            <textarea
                                                                className="input-field"
                                                                style={{ height: '80px', resize: 'vertical', fontSize: '13px', paddingTop: '8px' }}
                                                                value={selectedAgent.description || ''}
                                                                onChange={e => updateField('description', e.target.value)}
                                                            />
                                                        </div>
                                                    </div>


                                                    <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #f3f4f6' }}>
                                                        <Toggle
                                                            checked={!!selectedAgent.enable_bootstrap}
                                                            onChange={val => updateField('enable_bootstrap', val)}
                                                            label="On-demand Agent/Skills Provisioning"
                                                        />
                                                    </div>

                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>PERMISSIONS</h4>
                                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                                                            <div>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '8px' }}>ALLOW LIST</label>
                                                                <TagList
                                                                    items={selectedAgent.permissions?.allow}
                                                                    onRemove={(item) => updateField('permissions', { ...selectedAgent.permissions, allow: selectedAgent.permissions.allow.filter(a => a !== item) })}
                                                                />
                                                                <CreatableSelect
                                                                    isMulti placeholder="Add Permission..."
                                                                    value={(selectedAgent.permissions?.allow || []).map(a => ({ value: a, label: a }))}
                                                                    onChange={(val) => updateField('permissions', { ...selectedAgent.permissions, allow: val ? val.map(v => v.value) : [] })}
                                                                    controlShouldRenderValue={false}
                                                                    styles={{ control: (base) => ({ ...base, fontSize: '13px' }) }}
                                                                />
                                                            </div>
                                                            <div>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '8px' }}>DENY LIST</label>
                                                                <TagList
                                                                    items={selectedAgent.permissions?.deny}
                                                                    onRemove={(item) => updateField('permissions', { ...selectedAgent.permissions, deny: selectedAgent.permissions.deny.filter(d => d !== item) })}
                                                                />
                                                                <CreatableSelect
                                                                    isMulti placeholder="Add Permission..."
                                                                    value={(selectedAgent.permissions?.deny || []).map(d => ({ value: d, label: d }))}
                                                                    onChange={(val) => updateField('permissions', { ...selectedAgent.permissions, deny: val ? val.map(v => v.value) : [] })}
                                                                    controlShouldRenderValue={false}
                                                                    styles={{ control: (base) => ({ ...base, fontSize: '13px' }) }}
                                                                />
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'hitl' && (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>HITL (HUMAN IN THE LOOP)</h4>
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                                            <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>HITL MODE</label>
                                                            <div style={{ display: 'flex', gap: '8px' }}>
                                                                {[
                                                                    { value: 'on_request', label: 'On Request', desc: 'Ask when needed' },
                                                                    { value: 'always', label: 'Always', desc: 'Ask every turn' },
                                                                    { value: 'notify', label: 'Notify', desc: 'Notify only' },
                                                                    { value: 'never', label: 'Never', desc: 'Disable HITL' }
                                                                ].map(opt => (
                                                                    <button
                                                                        key={opt.value}
                                                                        onClick={() => updateField('hitl_mode', opt.value)}
                                                                        style={{
                                                                            flex: 1, padding: '8px 4px', borderRadius: '8px', border: '1px solid',
                                                                            borderColor: (selectedAgent.hitl_mode || 'on_request') === opt.value ? '#3b82f6' : '#e5e7eb',
                                                                            background: (selectedAgent.hitl_mode || 'on_request') === opt.value ? '#eff6ff' : 'white',
                                                                            color: (selectedAgent.hitl_mode || 'on_request') === opt.value ? '#1d4ed8' : '#64748b',
                                                                            cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', transition: 'all 0.2s'
                                                                        }}
                                                                    >
                                                                        <span style={{ fontSize: '12px', fontWeight: 700 }}>{opt.label}</span>
                                                                        <span style={{ fontSize: '9px', opacity: 0.8 }}>{opt.desc}</span>
                                                                    </button>
                                                                ))}
                                                            </div>
                                                        </div>
                                                    </div>

                                                    {(selectedAgent.hitl_mode !== 'never') && (
                                                        <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                                                                <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>HITL CHANNELS</h4>
                                                                <button
                                                                    className="btn" style={{ height: '28px', fontSize: '12px', padding: '0 12px' }}
                                                                    onClick={() => {
                                                                        const channels = selectedAgent.hitl_channels || [];
                                                                        updateField('hitl_channels', [...channels, { ref: 'new-channel', type: 'lark' }]);
                                                                    }}
                                                                >
                                                                    <Plus size={14} /> Add Channel
                                                                </button>
                                                            </div>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                                {(selectedAgent.hitl_channels || []).map((channel, idx) => (
                                                                    <HitlChannelCard
                                                                        key={idx}
                                                                        channel={channel}
                                                                        availableRefs={[...new Set([...globalHitlChannels, ...(selectedAgent.autonomy?.triggers || []).flatMap(t => (t.hitl_channels || []).map(c => c.ref))])]}
                                                                        onUpdate={(val) => {
                                                                            const newChannels = [...selectedAgent.hitl_channels];
                                                                            newChannels[idx] = val;
                                                                            updateField('hitl_channels', newChannels);
                                                                        }}
                                                                        onDelete={() => {
                                                                            const newChannels = selectedAgent.hitl_channels.filter((_, i) => i !== idx);
                                                                            updateField('hitl_channels', newChannels);
                                                                        }}
                                                                    />
                                                                ))}
                                                                {(selectedAgent.hitl_channels || []).length === 0 && (
                                                                    <div style={{ padding: '32px', textAlign: 'center', color: '#94a3b8', background: '#f8fafc', borderRadius: '12px', border: '1px dashed #e2e8f0', fontSize: '13px' }}>
                                                                        <Share2 size={32} style={{ margin: '0 auto 12px', opacity: 0.3 }} />
                                                                        <div>Using default chat channel.</div>
                                                                        <div style={{ fontSize: '12px', opacity: 0.8 }}>Add external channels like Lark or Slack to receive notifications and approve actions.</div>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            )}

                                            {activeSubTab === 'instructions' && (
                                                <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                    <div style={{ padding: '20px 24px', borderBottom: '1px solid #f1f5f9' }}>
                                                        <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>SYSTEM INSTRUCTIONS</h4>
                                                    </div>
                                                    <div style={{ flex: 1, padding: '0', display: 'flex' }}>
                                                        <textarea
                                                            className="input-field"
                                                            style={{
                                                                width: '100%',
                                                                flex: 1,
                                                                resize: 'none',
                                                                lineHeight: '1.6',
                                                                fontSize: '13px',
                                                                background: '#fafafa',
                                                                fontFamily: 'monospace',
                                                                border: 'none',
                                                                padding: '24px',
                                                                borderRadius: '0 0 12px 12px'
                                                            }}
                                                            placeholder="Enter system instructions here..."
                                                            value={selectedAgent.instructions || ''}
                                                            onChange={e => updateField('instructions', e.target.value)}
                                                        />
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'tools' && (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>SKILLS & CAPABILITIES</h4>
                                                        <SelectedList
                                                            items={selectedAgent.skills}
                                                            onRemove={(item) => updateField('skills', selectedAgent.skills.filter(s => s !== item))}
                                                            allItems={allSkills}
                                                        />
                                                        <Select
                                                            isMulti options={allSkills}
                                                            value={(selectedAgent.skills || []).map(s => ({ value: s, label: s }))}
                                                            onChange={(val) => updateField('skills', val ? val.map(v => v.value) : [])}
                                                            closeMenuOnSelect={false} hideSelectedOptions={true} controlShouldRenderValue={false}
                                                            styles={{ control: (base) => ({ ...base, fontSize: '13px' }) }}
                                                            placeholder="Select skills..."
                                                        />
                                                    </div>

                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>TOOLS</h4>
                                                        <SelectedList
                                                            items={selectedAgent.tools}
                                                            onRemove={(item) => updateField('tools', selectedAgent.tools.filter(t => t !== item))}
                                                            allItems={allTools}
                                                        />
                                                        <Select
                                                            isMulti options={allTools}
                                                            value={(selectedAgent.tools || []).map(t => ({ value: t, label: t }))}
                                                            onChange={(val) => updateField('tools', val ? val.map(v => v.value) : [])}
                                                            closeMenuOnSelect={false} hideSelectedOptions={true} controlShouldRenderValue={false}
                                                            styles={{ control: (base) => ({ ...base, fontSize: '13px' }) }}
                                                            placeholder="Select tools..."
                                                        />
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'workflow' && (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                                                            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>WORKFLOW (DAG) COORDINATOR</h4>
                                                            <Toggle
                                                                checked={!!selectedAgent.workflow?.enable}
                                                                onChange={val => {
                                                                    const workflow = selectedAgent.workflow || { enable: false, max_replans: 3, max_parallel: 5 };
                                                                    updateField('workflow', { ...workflow, enable: val });
                                                                }}
                                                                label="ENABLE WORKFLOW"
                                                            />
                                                        </div>
                                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>MAX REPLANS</label>
                                                                <input type="number" className="input-field" value={selectedAgent.workflow?.max_replans ?? 3} onChange={e => updateField('workflow', { ...selectedAgent.workflow, max_replans: parseInt(e.target.value) })} />
                                                            </div>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>MAX PARALLEL</label>
                                                                <input type="number" className="input-field" value={selectedAgent.workflow?.max_parallel ?? 5} onChange={e => updateField('workflow', { ...selectedAgent.workflow, max_parallel: parseInt(e.target.value) })} />
                                                            </div>
                                                        </div>
                                                        <div style={{ marginTop: '20px', padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                                                            <div style={{ fontSize: '12px', color: '#64748b', lineHeight: '1.5' }}>
                                                                <strong>DAG Mode:</strong> When enabled, this agent will act as a coordinator that can decompose complex tasks into sub-tasks and manage their execution across available sub-agents.
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'sub_agents' && (
                                                <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                                                        <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>SUB-AGENTS</h4>
                                                        <button className="btn" style={{ height: '28px', fontSize: '12px', padding: '0 12px' }} onClick={() => setAddSubAgentModal({ isOpen: true })}>
                                                            <Plus size={14} /> Add Sub-agent
                                                        </button>
                                                    </div>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                                        {Object.entries(selectedAgent.sub_agents || {}).map(([name, spec]) => (
                                                            <SubAgentCard
                                                                key={name} name={name} spec={spec}
                                                                agents={agents.filter(a => a.uuid !== selectedAgent.uuid)}
                                                                allSkills={allSkills} allTools={allTools}
                                                                onUpdate={(field, value) => updateSubAgentField(name, field, value)}
                                                                onDelete={() => {
                                                                    const sub_agents = { ...selectedAgent.sub_agents };
                                                                    delete sub_agents[name];
                                                                    updateField('sub_agents', sub_agents);
                                                                }}
                                                            />
                                                        ))}
                                                        {Object.keys(selectedAgent.sub_agents || {}).length === 0 && (
                                                            <div style={{ padding: '24px', textAlign: 'center', color: '#94a3b8', background: '#f8fafc', borderRadius: '8px', border: '1px dashed #e2e8f0', fontSize: '13px' }}>
                                                                No sub-agents configured.
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'mcp' && (
                                                <div style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', background: 'white', borderRadius: '12px', border: '1px solid #e5e7eb' }}>
                                                    <div style={{ textAlign: 'center' }}>
                                                        <Share2 size={48} style={{ marginBottom: '16px', opacity: 0.5 }} />
                                                        <div style={{ fontSize: '16px', fontWeight: 600 }}>MCP Integration</div>
                                                        <div style={{ fontSize: '13px' }}>Coming Soon...</div>
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'knowledge' && (
                                                <div style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', background: 'white', borderRadius: '12px', border: '1px solid #e5e7eb' }}>
                                                    <div style={{ textAlign: 'center' }}>
                                                        <Book size={48} style={{ marginBottom: '16px', opacity: 0.5 }} />
                                                        <div style={{ fontSize: '16px', fontWeight: 600 }}>Knowledge Base</div>
                                                        <div style={{ fontSize: '13px' }}>Coming Soon...</div>
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'daemon' && (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                                    {/* General Autonomy Settings */}
                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                                                            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>AUTONOMY CONFIG</h4>
                                                            <Toggle
                                                                checked={!!selectedAgent.autonomy?.enabled}
                                                                onChange={val => updateField('autonomy', { ...selectedAgent.autonomy, enabled: val })}
                                                                label="ENABLE AUTONOMY"
                                                            />
                                                        </div>

                                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>CONTROL LEVEL</label>
                                                                <div style={{ display: 'flex', gap: '8px' }}>
                                                                    {[
                                                                        { value: 'autonomous', label: 'Autonomous', desc: 'No notification' },
                                                                        { value: 'supervised', label: 'Supervised', desc: 'Notify after' },
                                                                        { value: 'collaborative', label: 'Collaborate', desc: 'Pre-approval' }
                                                                    ].map(opt => (
                                                                        <button
                                                                            key={opt.value}
                                                                            onClick={() => updateField('autonomy', { ...selectedAgent.autonomy, level: opt.value })}
                                                                            style={{
                                                                                flex: 1, padding: '8px 4px', borderRadius: '8px', border: '1px solid',
                                                                                borderColor: (selectedAgent.autonomy?.level || 'supervised') === opt.value ? '#3b82f6' : '#e5e7eb',
                                                                                background: (selectedAgent.autonomy?.level || 'supervised') === opt.value ? '#eff6ff' : 'white',
                                                                                color: (selectedAgent.autonomy?.level || 'supervised') === opt.value ? '#1d4ed8' : '#64748b',
                                                                                cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', transition: 'all 0.2s'
                                                                            }}
                                                                        >
                                                                            <span style={{ fontSize: '12px', fontWeight: 700 }}>{opt.label}</span>
                                                                            <span style={{ fontSize: '9px', opacity: 0.8 }}>{opt.desc}</span>
                                                                        </button>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>TICK INTERVAL (S)</label>
                                                                <input type="number" className="input-field" value={selectedAgent.autonomy?.tick_interval ?? 3600} onChange={e => updateField('autonomy', { ...selectedAgent.autonomy, tick_interval: parseInt(e.target.value) })} />
                                                            </div>
                                                        </div>

                                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginTop: '16px' }}>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>STRATEGY</label>
                                                                <select className="input-field" value={selectedAgent.autonomy?.instance_strategy || 'queue'} onChange={e => updateField('autonomy', { ...selectedAgent.autonomy, instance_strategy: e.target.value })}>
                                                                    <option value="queue">Queue</option>
                                                                    <option value="parallel">Parallel</option>
                                                                    <option value="replace">Replace</option>
                                                                </select>
                                                            </div>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>THINK MODEL</label>
                                                                <input className="input-field" value={selectedAgent.autonomy?.think_model || 'fast'} onChange={e => updateField('autonomy', { ...selectedAgent.autonomy, think_model: e.target.value })} />
                                                            </div>
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>ACT MODEL</label>
                                                                <input className="input-field" value={selectedAgent.autonomy?.act_model || 'smart'} onChange={e => updateField('autonomy', { ...selectedAgent.autonomy, act_model: e.target.value })} />
                                                            </div>
                                                        </div>
                                                    </div>

                                                    {/* Triggers Section */}
                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                                                            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>TRIGGERS</h4>
                                                            <button
                                                                className="btn"
                                                                style={{ height: '28px', fontSize: '12px', padding: '0 12px' }}
                                                                onClick={() => {
                                                                    const triggers = selectedAgent.autonomy?.triggers || [];
                                                                    updateField('autonomy', { ...selectedAgent.autonomy, triggers: [...triggers, { id: `trg_${Date.now()}`, type: 'interval', every: 3600, task: '' }] });
                                                                }}
                                                            >
                                                                <Plus size={14} /> Add Trigger
                                                            </button>
                                                        </div>

                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                            {(selectedAgent.autonomy?.triggers || []).map((trigger, idx) => (
                                                                <div key={trigger.id || idx} style={{ padding: '16px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', position: 'relative' }}>
                                                                    <button
                                                                        onClick={() => {
                                                                            const newTriggers = selectedAgent.autonomy.triggers.filter((_, i) => i !== idx);
                                                                            updateField('autonomy', { ...selectedAgent.autonomy, triggers: newTriggers });
                                                                        }}
                                                                        style={{ position: 'absolute', top: '8px', right: '8px', border: 'none', background: 'none', color: '#94a3b8', padding: '4px', cursor: 'pointer', transition: 'color 0.2s' }}
                                                                        onMouseOver={e => e.currentTarget.style.color = '#ef4444'}
                                                                        onMouseOut={e => e.currentTarget.style.color = '#94a3b8'}
                                                                    >
                                                                        <X size={16} />
                                                                    </button>

                                                                    <div style={{ display: 'flex', gap: '12px', marginBottom: '12px', alignItems: 'center', paddingRight: '24px' }}>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '120px' }}>
                                                                            <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>TRIGGER TYPE</label>
                                                                            <select
                                                                                className="input-field"
                                                                                style={{ height: '32px', padding: '0 12px' }}
                                                                                value={trigger.type}
                                                                                onChange={e => {
                                                                                    const newTriggers = [...selectedAgent.autonomy.triggers];
                                                                                    newTriggers[idx] = { ...trigger, type: e.target.value };
                                                                                    updateField('autonomy', { ...selectedAgent.autonomy, triggers: newTriggers });
                                                                                }}
                                                                            >
                                                                                <option value="cron">Cron</option>
                                                                                <option value="interval">Interval</option>
                                                                            </select>
                                                                        </div>
                                                                        {trigger.type === 'cron' && (
                                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
                                                                                <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>SCHEDULE (CRON)</label>
                                                                                <input className="input-field" style={{ height: '32px', padding: '0 12px' }} value={trigger.schedule || ''} onChange={e => {
                                                                                    const nt = [...selectedAgent.autonomy.triggers]; nt[idx].schedule = e.target.value;
                                                                                    updateField('autonomy', { ...selectedAgent.autonomy, triggers: nt });
                                                                                }} />
                                                                            </div>
                                                                        )}
                                                                        {trigger.type === 'interval' && (
                                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
                                                                                <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>EVERY (SECONDS)</label>
                                                                                <input type="number" className="input-field" style={{ height: '32px', padding: '0 12px' }} value={trigger.every || 0} onChange={e => {
                                                                                    const nt = [...selectedAgent.autonomy.triggers]; nt[idx].every = parseInt(e.target.value);
                                                                                    updateField('autonomy', { ...selectedAgent.autonomy, triggers: nt });
                                                                                }} />
                                                                            </div>
                                                                        )}
                                                                    </div>

                                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                                        <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>TASK DESCRIPTION</label>
                                                                        <textarea
                                                                            className="input-field"
                                                                            style={{ minHeight: '60px', padding: '8px 12px', fontSize: '12px', resize: 'vertical' }}
                                                                            value={trigger.task || ''}
                                                                            onChange={e => {
                                                                                const nt = [...selectedAgent.autonomy.triggers]; nt[idx].task = e.target.value;
                                                                                updateField('autonomy', { ...selectedAgent.autonomy, triggers: nt });
                                                                            }}
                                                                        />
                                                                    </div>
                                                                    <div style={{ marginTop: '12px' }}>
                                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                                                            <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>TRIGGER HITL CHANNELS</label>
                                                                            <button
                                                                                className="btn"
                                                                                style={{ height: '24px', fontSize: '10px', padding: '0 8px', background: 'white' }}
                                                                                onClick={() => {
                                                                                    const nt = [...selectedAgent.autonomy.triggers];
                                                                                    nt[idx].hitl_channels = [...(nt[idx].hitl_channels || []), { ref: 'new-channel', type: 'lark' }];
                                                                                    updateField('autonomy', { ...selectedAgent.autonomy, triggers: nt });
                                                                                }}
                                                                            >
                                                                                <Plus size={12} /> Add Channel
                                                                            </button>
                                                                        </div>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                                                            {(trigger.hitl_channels || []).map((channel, cIdx) => (
                                                                                <HitlChannelCard
                                                                                    key={`trg_${idx}_ch_${cIdx}`}
                                                                                    channel={channel}
                                                                                    availableRefs={[...new Set([...globalHitlChannels, ...(selectedAgent.hitl_channels || []).map(c => c.ref)])]}
                                                                                    onUpdate={(val) => {
                                                                                        const nt = [...selectedAgent.autonomy.triggers];
                                                                                        nt[idx].hitl_channels[cIdx] = val;
                                                                                        updateField('autonomy', { ...selectedAgent.autonomy, triggers: nt });
                                                                                    }}
                                                                                    onDelete={() => {
                                                                                        const nt = [...selectedAgent.autonomy.triggers];
                                                                                        nt[idx].hitl_channels = nt[idx].hitl_channels.filter((_, i) => i !== cIdx);
                                                                                        updateField('autonomy', { ...selectedAgent.autonomy, triggers: nt });
                                                                                    }}
                                                                                />
                                                                            ))}
                                                                            {(trigger.hitl_channels || []).length === 0 && (
                                                                                <div style={{ padding: '8px', textAlign: 'center', color: '#94a3b8', fontSize: '10px', background: 'rgba(255,255,255,0.5)', borderRadius: '6px', border: '1px dashed #e2e8f0' }}>
                                                                                    Defaults to agent's HITL channels or standard logic.
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                            {(selectedAgent.autonomy?.triggers || []).length === 0 && (
                                                                <div style={{ padding: '20px', textAlign: 'center', color: '#94a3b8', background: '#f8fafc', borderRadius: '8px', fontSize: '12px' }}>
                                                                    No triggers configured.
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* Goals Section */}
                                                    <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                                                            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>GOALS</h4>
                                                            <button
                                                                className="btn"
                                                                style={{ height: '28px', fontSize: '12px', padding: '0 12px' }}
                                                                onClick={() => {
                                                                    const goals = selectedAgent.autonomy?.goals || [];
                                                                    updateField('autonomy', { ...selectedAgent.autonomy, goals: [...goals, { id: `goal_${Date.now()}`, description: '', priority: 'normal' }] });
                                                                }}
                                                            >
                                                                <Plus size={14} /> Add Goal
                                                            </button>
                                                        </div>

                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                            {(selectedAgent.autonomy?.goals || []).map((goal, idx) => (
                                                                <div key={goal.id || idx} style={{ padding: '16px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', position: 'relative' }}>
                                                                    <button
                                                                        onClick={() => {
                                                                            const ng = selectedAgent.autonomy.goals.filter((_, i) => i !== idx);
                                                                            updateField('autonomy', { ...selectedAgent.autonomy, goals: ng });
                                                                        }}
                                                                        style={{ position: 'absolute', top: '8px', right: '8px', border: 'none', background: 'none', color: '#94a3b8', padding: '4px', cursor: 'pointer', transition: 'color 0.2s' }}
                                                                        onMouseOver={e => e.currentTarget.style.color = '#ef4444'}
                                                                        onMouseOut={e => e.currentTarget.style.color = '#94a3b8'}
                                                                    >
                                                                        <X size={16} />
                                                                    </button>

                                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '12px', paddingRight: '24px' }}>
                                                                        <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>GOAL DESCRIPTION</label>
                                                                        <textarea
                                                                            className="input-field"
                                                                            style={{ minHeight: '60px', padding: '8px 12px', fontSize: '12px', resize: 'vertical' }}
                                                                            placeholder="What should the agent achieve?"
                                                                            value={goal.description}
                                                                            onChange={e => {
                                                                                const ng = [...selectedAgent.autonomy.goals]; ng[idx].description = e.target.value;
                                                                                updateField('autonomy', { ...selectedAgent.autonomy, goals: ng });
                                                                            }}
                                                                        />
                                                                    </div>

                                                                    <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
                                                                            <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>SUCCESS CRITERIA</label>
                                                                            <input
                                                                                className="input-field"
                                                                                style={{ height: '32px', padding: '0 12px' }}
                                                                                placeholder="How to verify success?"
                                                                                value={goal.success_criteria || ''}
                                                                                onChange={e => {
                                                                                    const ng = [...selectedAgent.autonomy.goals]; ng[idx].success_criteria = e.target.value;
                                                                                    updateField('autonomy', { ...selectedAgent.autonomy, goals: ng });
                                                                                }}
                                                                            />
                                                                        </div>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '120px' }}>
                                                                            <label style={{ fontSize: '9px', fontWeight: 600, color: '#94a3b8' }}>PRIORITY</label>
                                                                            <select
                                                                                className="input-field"
                                                                                style={{ height: '32px', padding: '0 12px' }}
                                                                                value={goal.priority}
                                                                                onChange={e => {
                                                                                    const ng = [...selectedAgent.autonomy.goals]; ng[idx].priority = e.target.value;
                                                                                    updateField('autonomy', { ...selectedAgent.autonomy, goals: ng });
                                                                                }}
                                                                            >
                                                                                <option value="high">High</option>
                                                                                <option value="normal">Normal</option>
                                                                                <option value="low">Low</option>
                                                                            </select>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                            {(selectedAgent.autonomy?.goals || []).length === 0 && (
                                                                <div style={{ padding: '20px', textAlign: 'center', color: '#94a3b8', background: '#f8fafc', borderRadius: '8px', fontSize: '12px' }}>
                                                                    No goals configured.
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'sessions' && (
                                                <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                    <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>ACTIVE SESSIONS</h4>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                        {agentSessions.length === 0 ? (
                                                            <div style={{ padding: '40px', textAlign: 'center', color: '#94a3b8', fontSize: '13px' }}>
                                                                No active sessions for this agent.
                                                            </div>
                                                        ) : (
                                                            agentSessions.map(session => (
                                                                <div key={session.session_id}
                                                                    className="list-item"
                                                                    onClick={() => navigate(`/sessions?session_id=${session.session_id}`)}
                                                                    style={{ padding: '16px', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                                                                >
                                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                                                        <MessageSquare size={16} color="#64748b" />
                                                                        <div>
                                                                            <div style={{ fontWeight: 600, fontSize: '14px' }}>{session.metadata?.title || 'Untitled Session'}</div>
                                                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                                                <span style={{ fontSize: '10px', color: '#94a3b8', fontFamily: 'monospace' }}>{session.session_id}</span>
                                                                                <span style={{ fontSize: '10px', color: '#cbd5e1' }}>•</span>
                                                                                <span style={{ fontSize: '10px', color: '#94a3b8' }}>{new Date(session.updated_at || Date.now()).toLocaleString()}</span>
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                    <ChevronRight size={16} color="#94a3b8" />
                                                                </div>
                                                            ))
                                                        )}
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'loops' && (
                                                <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                    <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>AUTONOMOUS LOOPS</h4>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                        {agentLoops.length === 0 ? (
                                                            <div style={{ padding: '40px', textAlign: 'center', color: '#94a3b8', fontSize: '13px' }}>
                                                                No active autonomous loops for this agent.
                                                            </div>
                                                        ) : (
                                                            agentLoops.map(loop => (
                                                                <div key={loop.name} style={{ padding: '16px', border: '1px solid #e2e8f0', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                                                        <div style={{
                                                                            width: '10px', height: '10px', borderRadius: '50%',
                                                                            background: loop.running ? '#10b981' : '#f59e0b'
                                                                        }} />
                                                                        <div>
                                                                            <div style={{ fontWeight: 600, fontSize: '14px' }}>{loop.name}</div>
                                                                            <div style={{ fontSize: '12px', color: '#64748b' }}>
                                                                                Status: {loop.running ? 'Running' : 'Stopped'} |
                                                                                Level: {loop.level || 'N/A'}
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                    <div style={{ fontSize: '11px', fontWeight: 600, color: loop.running ? '#10b981' : '#f59e0b', background: loop.running ? '#f0fdf4' : '#fff7ed', padding: '4px 8px', borderRadius: '12px' }}>
                                                                        {loop.running ? 'ACTIVE' : 'INACTIVE'}
                                                                    </div>
                                                                </div>
                                                            ))
                                                        )}
                                                    </div>
                                                </div>
                                            )}

                                            {activeSubTab === 'memory' && (
                                                <div className="card" style={{ padding: '20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
                                                    <h4 style={{ margin: '0 0 16px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>MEMORY</h4>
                                                    <div style={{ padding: '40px', textAlign: 'center', color: '#94a3b8', fontSize: '13px' }}>
                                                        No episodic or long-term memory recorded yet for this agent.
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        <AddSubAgentModal
                            isOpen={addSubAgentModal.isOpen}
                            onClose={() => setAddSubAgentModal({ isOpen: false })}
                            agents={agents.filter(a => a.uuid !== selectedAgent.uuid)}
                            onAdd={(name, ref_uuid) => {
                                const sub_agents = { ...selectedAgent.sub_agents };
                                sub_agents[name] = {
                                    description: '',
                                    adviced_model_kind: 'smart',
                                    max_turns: 20,
                                    ref_uuid: ref_uuid || null
                                };
                                updateField('sub_agents', sub_agents);
                            }}
                        />
                    </div>
                ) : (
                    <div style={{ flex: 1, display: 'flex' }}>
                        {filteredAgents.length === 0 ? (
                            <EmptyState
                                icon={Bot}
                                title={sourceTab === 'custom' ? "No custom agents yet" : "No agents found"}
                                description={
                                    sourceTab === 'custom'
                                        ? "Create your first agent to get started. Use the Agent Architect to design and build custom agents tailored to your workflow."
                                        : "There are no built-in agents available in this category. Check other tabs or try refreshing the page."
                                }
                                actionLabel={sourceTab === 'custom' ? "Create Agent" : null}
                                onAction={sourceTab === 'custom' ? handleCreate : null}
                            />
                        ) : (
                            <EmptyState
                                icon={Layout}
                                title="Select an Agent"
                                description="Choose an agent from the list on the left to view its configuration, manage its skills, and monitor its activity."
                            />
                        )}
                    </div>
                )}
            </div>

            <SaveModal isOpen={saveModal.isOpen} result={saveModal.result} onClose={() => setSaveModal({ isOpen: false, result: { status: '', message: '' } })} />
            <DeleteModal isOpen={deleteModal.isOpen} agent={deleteModal.agent} onConfirm={handleDelete} onClose={() => setDeleteModal({ isOpen: false, agent: null })} />
        </div>
    );
}

function AddSubAgentModal({ isOpen, onClose, onAdd, agents }) {
    const [name, setName] = useState('');
    const [refUuid, setRefUuid] = useState('');
    const [mode, setMode] = useState('link'); // 'link' or 'custom'

    if (!isOpen) return null;

    const handleAdd = () => {
        if (!name) return;
        onAdd(name, mode === 'link' ? refUuid : null);
        setName('');
        setRefUuid('');
        onClose();
    };

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000
        }}>
            <div style={{ background: 'white', borderRadius: '12px', width: '400px', padding: '24px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                    <UserPlus size={18} color="#3b82f6" />
                    <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>Add Sub-agent</h3>
                </div>

                <div style={{ display: 'flex', background: '#f1f5f9', padding: '2px', borderRadius: '8px', marginBottom: '20px', gap: '2px' }}>
                    <button
                        onClick={() => setMode('link')}
                        style={{ flex: 1, padding: '6px', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: 600, background: mode === 'link' ? 'white' : 'transparent', color: mode === 'link' ? '#111827' : '#64748b', cursor: 'pointer', transition: 'all 0.2s' }}>
                        Linked Agent
                    </button>
                    <button
                        onClick={() => setMode('custom')}
                        style={{ flex: 1, padding: '6px', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: 600, background: mode === 'custom' ? 'white' : 'transparent', color: mode === 'custom' ? '#111827' : '#64748b', cursor: 'pointer', transition: 'all 0.2s' }}>
                        Ad-hoc Custom
                    </button>
                </div>

                {mode === 'link' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                        <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>SELECT AGENT</label>
                        <select
                            className="input-field"
                            style={{ height: '36px', fontSize: '13px' }}
                            value={refUuid}
                            onChange={e => {
                                setRefUuid(e.target.value);
                                const agent = agents.find(a => a.uuid === e.target.value);
                                if (agent && !name) {
                                    setName(agent.agent_name.toLowerCase().replace(/[^a-z0-9_]/g, '_'));
                                }
                            }}
                        >
                            <option value="">-- Select an Agent --</option>
                            {agents.map(a => <option key={a.uuid} value={a.uuid}>{a.agent_name} (v{a.version})</option>)}
                        </select>
                    </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '24px' }}>
                    <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>IDENTIFIER NAME</label>
                    <input
                        autoFocus={mode === 'custom'}
                        className="input-field"
                        placeholder="e.g. data_analyst"
                        value={name}
                        onChange={e => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'))}
                        onKeyDown={e => { if (e.key === 'Enter') handleAdd(); }}
                    />
                    <span style={{ fontSize: '10px', color: '#94a3b8' }}>This will be the key in the sub_agents dictionary.</span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                    <button className="btn" onClick={onClose}>Cancel</button>
                    <button
                        className="btn btn-primary"
                        disabled={!name || (mode === 'link' && !refUuid)}
                        onClick={handleAdd}
                    >
                        Add Sub-agent
                    </button>
                </div>
            </div>
        </div>
    );
}
