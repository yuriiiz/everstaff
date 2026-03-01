import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import { Save, ArrowLeft } from 'lucide-react';
import LoadingView from '../components/LoadingView';

export default function AgentEditor() {
    const { uuid } = useParams();
    const navigate = useNavigate();
    const [yamlContent, setYamlContent] = useState('');
    const [loading, setLoading] = useState(!!uuid);

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
                <button onClick={handleSave} className="btn btn-primary">
                    <Save size={16} /> Save
                </button>
            </div>

            <div className="card" style={{ flex: 1, padding: 0, overflow: 'hidden' }}>
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
            </div>
        </div>
    );
}
