import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import { Save, ArrowLeft } from 'lucide-react';
import LoadingView from '../components/LoadingView';

export default function ToolEditor() {
    const { toolName } = useParams();
    const navigate = useNavigate();
    const [code, setCode] = useState('');
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch(`/api/tools/${toolName}/code`)
            .then(res => {
                if (!res.ok) throw new Error("Not found");
                return res.json();
            })
            .then(data => {
                setCode(data.code);
                setLoading(false);
            })
            .catch(err => {
                alert(err.message);
                navigate('/skills');
            });
    }, [toolName]);

    const handleSave = () => {
        fetch(`/api/tools/${toolName}/code`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        })
            .then(res => {
                if (res.ok) alert("Saved!");
                else alert("Failed to save");
            });
    };

    if (loading) return <LoadingView message="Loading Tool Editor..." />;

    return (
        <div style={{ height: 'calc(100vh - 100px)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <button onClick={() => navigate('/skills')} className="btn"><ArrowLeft size={16} /></button>
                    <h2 style={{ margin: 0, fontWeight: 600 }}>Edit Tool: {toolName}</h2>
                </div>
                <button onClick={handleSave} className="btn btn-primary">
                    <Save size={16} /> Save
                </button>
            </div>

            <div className="card" style={{ flex: 1, padding: 0, overflow: 'hidden' }}>
                <Editor
                    height="100%"
                    defaultLanguage="python"
                    theme="light"
                    value={code}
                    onChange={setCode}
                    options={{
                        minimap: { enabled: false },
                        fontSize: 14,
                    }}
                />
            </div>
        </div>
    );
}
