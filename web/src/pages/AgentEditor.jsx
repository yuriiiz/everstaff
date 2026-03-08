import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import { Save, ArrowLeft, Settings, Brain } from 'lucide-react';
import LoadingView from '../components/LoadingView';
import MemoryList from '../components/MemoryList';

export default function AgentEditor() {
    const { uuid } = useParams();
    const navigate = useNavigate();
    const [yamlContent, setYamlContent] = useState('');
    const [loading, setLoading] = useState(!!uuid && uuid !== 'new');
    const [activeTab, setActiveTab] = useState('config'); // 'config' | 'memory'

    useEffect(() => {
        if (uuid && uuid !== 'new') {
            fetch(`/api/agents/${uuid}`)
                .then(res => res.json())
                .then(data => {
                    setYamlContent(JSON.stringify(data, null, 2));
                    setLoading(false);
                });
        } else {
            setYamlContent(JSON.stringify({
                agent_name: "new-agent",
                version: "0.1.0",
                description: "New agent",
                adviced_model_kind: "smart",
                instructions: "You are a helpful assistant.",
                skills: [],
                tools: [],
                workflow: {
                    enable: false,
                    hitl_mode: "on_request",
                    max_replans: 3,
                    max_parallel: 5
                },
                sub_agents: {}
            }, null, 2));
        }
    }, [uuid]);

    const handleSave = () => {
        try {
            const spec = JSON.parse(yamlContent);
            const isNew = !uuid || uuid === 'new';
            const method = isNew ? 'POST' : 'PUT';
            const url = isNew ? '/api/agents' : `/api/agents/${uuid}`;

            fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(spec)
            })
                .then(res => {
                    if (res.ok) {
                        navigate('/');
                    } else {
                        alert("Failed to save");
                    }
                });
        } catch (e) {
            alert("Invalid JSON");
        }
    };

    if (loading) return <LoadingView message="Loading Agent Editor..." />;

    return (
        <div style={{ height: 'calc(100vh - 100px)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <button onClick={() => navigate('/')} className="btn"><ArrowLeft size={16} /></button>
                    <h2 style={{ margin: 0, fontWeight: 600 }}>
                        {uuid && uuid !== 'new'
                            ? `Edit Agent: ${(() => {
                                try { return JSON.parse(yamlContent).agent_name; } catch (e) { return '...'; }
                            })()}`
                            : 'New Agent'}
                    </h2>
                </div>

                {uuid && uuid !== 'new' && (
                    <div style={{ display: 'flex', background: '#e2e8f0', padding: '4px', borderRadius: '8px' }}>
                        <button
                            onClick={() => setActiveTab('config')}
                            style={{
                                display: 'flex', alignItems: 'center', gap: '8px',
                                padding: '6px 16px', borderRadius: '6px', fontSize: '14px', fontWeight: 600,
                                background: activeTab === 'config' ? 'white' : 'transparent',
                                color: activeTab === 'config' ? '#0f172a' : '#64748b',
                                boxShadow: activeTab === 'config' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                                border: 'none', cursor: 'pointer', transition: 'all 0.2s'
                            }}
                        >
                            <Settings size={16} /> Configuration
                        </button>
                        <button
                            onClick={() => setActiveTab('memory')}
                            style={{
                                display: 'flex', alignItems: 'center', gap: '8px',
                                padding: '6px 16px', borderRadius: '6px', fontSize: '14px', fontWeight: 600,
                                background: activeTab === 'memory' ? 'white' : 'transparent',
                                color: activeTab === 'memory' ? '#0f172a' : '#64748b',
                                boxShadow: activeTab === 'memory' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                                border: 'none', cursor: 'pointer', transition: 'all 0.2s'
                            }}
                        >
                            <Brain size={16} /> Memory
                        </button>
                    </div>
                )}

                <button onClick={handleSave} className="btn btn-primary" style={{ visibility: activeTab === 'config' ? 'visible' : 'hidden' }}>
                    <Save size={16} /> Save
                </button>
            </div>

            <div className="card" style={{ flex: 1, padding: activeTab === 'memory' ? 0 : 0, overflow: 'hidden' }}>
                {activeTab === 'config' ? (
                    <Editor
                        height="100%"
                        defaultLanguage="json"
                        theme="light"
                        value={yamlContent}
                        onChange={setYamlContent}
                        options={{
                            minimap: { enabled: false },
                            fontSize: 14,
                        }}
                    />
                ) : (
                    <MemoryList agentUuid={uuid} />
                )}
            </div>
        </div>
    );
}
