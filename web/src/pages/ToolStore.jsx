import { useState, useEffect } from 'react';
import { Settings, FileCode, Info, Plus, Save, Trash2, X } from 'lucide-react';
import Editor from '@monaco-editor/react';

export default function ToolStore() {
    const [tools, setTools] = useState([]);
    const [selectedTool, setSelectedTool] = useState(null);
    const [toolCode, setToolCode] = useState('');
    const [toolContent, setToolContent] = useState('');
    const [loadingCode, setLoadingCode] = useState(false);
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [newToolName, setNewToolName] = useState('');
    const [newToolDescription, setNewToolDescription] = useState('');
    const [isSaving, setIsSaving] = useState(false);
    const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

    useEffect(() => {
        fetchTools();
    }, []);

    const fetchTools = () => {
        fetch('/api/tools')
            .then(res => res.json())
            .then(data => {
                setTools(data);
                if (data.length > 0 && !selectedTool) handleSelectTool(data[0]);
                else if (selectedTool) {
                    const updated = data.find(t => t.name === selectedTool.name);
                    if (updated) setSelectedTool(updated);
                }
            });
    };

    const handleSelectTool = (tool) => {
        setSelectedTool(tool);
        setLoadingCode(true);
        setToolCode('');
        setToolContent('');

        fetch(`/api/tools/${tool.name}`)
            .then(res => res.json())
            .then(data => {
                if (data.content) {
                    setToolCode(data.content);
                    setToolContent(data.content);
                    // Extract info from content if not provided by backend
                    if (!tool.description || !tool.parameters) {
                        const description = data.content.match(/description=["'](.*?)["']/)?.[1] || tool.description;
                        // Simple regex for parameters: looks for def name(args)
                        const paramsMatch = data.content.match(/def\s+\w+\((.*?)\)/);
                        const params = paramsMatch ? paramsMatch[1].split(',').map(p => ({
                            name: p.split(':')[0].trim(),
                            type: p.split(':')[1]?.trim() || 'string'
                        })).filter(p => !['self', 'cls'].includes(p.name)) : [];

                        setSelectedTool(prev => ({ ...prev, description, parameters: params }));
                    }
                }
                else {
                    setToolCode('# Failed to load tool code');
                    setToolContent('');
                }
                setLoadingCode(false);
            })
            .catch(err => {
                console.error('Failed to fetch tool code:', err);
                setToolCode('# Error loading code');
                setToolContent('');
                setLoadingCode(false);
            });
    };

    const handleSaveCode = () => {
        if (!selectedTool) return;
        setIsSaving(true);
        fetch(`/api/tools/${selectedTool.name}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: toolCode })
        })
            .then(res => res.json())
            .then(() => {
                setIsSaving(false);
                // Optionally show toast
            })
            .catch(err => {
                console.error('Failed to save code:', err);
                setIsSaving(false);
            });
    };

    const handleCreateTool = () => {
        fetch('/api/tools', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newToolName, description: newToolDescription })
        })
            .then(res => res.json())
            .then(data => {
                setIsCreateModalOpen(false);
                setNewToolName('');
                setNewToolDescription('');
                fetchTools();
            })
            .catch(err => console.error('Failed to create tool:', err));
    };

    const handleDeleteTool = () => {
        if (!selectedTool) return;

        fetch(`/api/tools/${selectedTool.name}`, {
            method: 'DELETE'
        })
            .then(res => res.json())
            .then(() => {
                setSelectedTool(null);
                setToolCode('');
                setToolContent('');
                setIsDeleteModalOpen(false);
                fetchTools();
            })
            .catch(err => {
                console.error('Failed to delete tool:', err);
                setIsDeleteModalOpen(false);
            });
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#f9fafb' }}>
            <div style={{ flex: 1, overflow: 'hidden' }}>
                <div style={{ display: 'flex', height: '100%' }}>
                    {/* 1. Tools List */}
                    <div style={{ width: '300px', borderRight: '1px solid #e5e7eb', background: 'white', overflowY: 'auto' }}>
                        <div style={{ height: '60px', padding: '0 24px', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'white', position: 'sticky', top: 0, zIndex: 10 }}>
                            <h2 style={{ fontSize: '15px', color: '#111827', fontWeight: 700, margin: 0 }}>Tools</h2>
                            <button className="btn" style={{ padding: '4px 8px' }} onClick={() => setIsCreateModalOpen(true)} title="Add Tool"><Plus size={16} /></button>
                        </div>
                        {tools.map(t => (
                            <div
                                key={t.name}
                                onClick={() => handleSelectTool(t)}
                                style={{
                                    padding: '16px 20px', borderBottom: '1px solid #f3f4f6', cursor: 'pointer', transition: 'all 0.2s',
                                    background: selectedTool?.name === t.name ? '#f8fafc' : 'white',
                                    borderLeft: selectedTool?.name === t.name ? '4px solid #111827' : '4px solid transparent'
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                                    <Settings size={14} color={selectedTool?.name === t.name ? '#111827' : '#9ca3af'} />
                                    <div style={{ fontWeight: 700, fontSize: '14px', color: '#111827' }}>{t.name}</div>
                                </div>
                                <div style={{ fontSize: '12px', color: '#6b7280', lineHeight: '1.4', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                                    {t.description}
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Right Content Area */}
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: '#f9fafb' }}>
                        {selectedTool ? (
                            <>
                                {/* Global Header like AgentStore */}
                                <div className="header" style={{ height: '60px', flexShrink: 0, background: 'white', borderBottom: '1px solid #e5e7eb', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                        <h3 style={{ fontSize: '15px', color: '#111827', fontWeight: 700, margin: 0 }}>{selectedTool.name}</h3>
                                        <span style={{ fontSize: '10px', background: '#f8fafc', border: '1px solid #e2e8f0', color: '#475569', padding: '2px 6px', borderRadius: '4px', fontWeight: 700 }}>TOOL</span>
                                        {loadingCode && <span style={{ fontSize: '11px', color: '#94a3b8' }}>Loading...</span>}
                                    </div>
                                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                        <button className="btn" onClick={() => setIsDeleteModalOpen(true)} style={{ height: '36px', color: '#ef4444', border: 'none', background: 'none' }} title="Delete Tool">
                                            <Trash2 size={18} />
                                        </button>
                                        <button className="btn btn-primary" onClick={handleSaveCode} disabled={isSaving} style={{ gap: '8px', padding: '0 16px', height: '36px', borderRadius: '8px', fontSize: '13px', fontWeight: 600, opacity: isSaving ? 0.7 : 1 }}>
                                            <Save size={16} /> {isSaving ? 'Saving...' : 'Save'}
                                        </button>
                                    </div>
                                </div>

                                <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                                    {/* Code Viewer */}
                                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'white' }}>
                                        <div style={{ padding: '8px 16px', background: '#f8fafc', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: '8px', color: '#64748b', fontSize: '12px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                            <FileCode size={14} />
                                            <span>{selectedTool.name}.py</span>
                                        </div>
                                        <div style={{ flex: 1, overflow: 'hidden' }}>
                                            <Editor
                                                height="100%"
                                                defaultLanguage="python"
                                                theme="light"
                                                value={toolCode}
                                                onChange={(value) => setToolCode(value)}
                                                options={{
                                                    readOnly: false,
                                                    minimap: { enabled: false },
                                                    fontSize: 13,
                                                    lineNumbers: 'on',
                                                    scrollBeyondLastLine: false,
                                                    automaticLayout: true,
                                                    padding: { top: 16 }
                                                }}
                                            />
                                        </div>
                                    </div>

                                    {/* Tool Specification (Right Panel) */}
                                    <div style={{ width: '320px', borderLeft: '1px solid #e5e7eb', background: '#f8fafc', overflowY: 'auto', padding: '24px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px', fontSize: '12px', fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                            <Info size={14} />
                                            <span>Tool Specification</span>
                                        </div>

                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                                            <div>
                                                <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '8px' }}>Description</div>
                                                <p style={{ fontSize: '14px', color: '#4b5563', lineHeight: '1.6', margin: 0 }}>{selectedTool.description}</p>
                                            </div>

                                            <div>
                                                <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '12px' }}>Parameters</div>
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                    {selectedTool.parameters && selectedTool.parameters.length > 0 ? (
                                                        selectedTool.parameters.map(param => (
                                                            <div key={param.name} style={{ background: 'white', borderRadius: '8px', padding: '12px', border: '1px solid #e5e7eb' }}>
                                                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                                                    <span style={{ fontWeight: 700, fontSize: '13px', color: '#111827' }}>{param.name}</span>
                                                                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 600 }}>{param.type}</span>
                                                                </div>
                                                                <div style={{ fontSize: '12px', color: '#64748b' }}>{param.description}</div>
                                                                {param.required && (
                                                                    <div style={{ marginTop: '8px', fontSize: '10px', color: '#ef4444', fontWeight: 700 }}>REQUIRED</div>
                                                                )}
                                                            </div>
                                                        ))
                                                    ) : (
                                                        <div style={{ fontSize: '13px', color: '#94a3b8', fontStyle: 'italic' }}>No parameters defined.</div>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </>
                        ) : (
                            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '14px' }}>
                                Select a tool to view its code and specification
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Create Modal */}
            {isCreateModalOpen && (
                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(4px)' }}>
                    <div style={{ background: 'white', borderRadius: '16px', padding: '32px', width: '450px', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', border: '1px solid #e5e7eb' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                            <h2 style={{ fontSize: '20px', fontWeight: 800, color: '#111827', margin: 0 }}>Create New Tool</h2>
                            <X size={20} style={{ cursor: 'pointer', color: '#9ca3af' }} onClick={() => setIsCreateModalOpen(false)} />
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                            <div>
                                <label style={{ display: 'block', fontSize: '12px', fontWeight: 700, color: '#4b5563', marginBottom: '8px', textTransform: 'uppercase' }}>Tool Name</label>
                                <input
                                    type="text"
                                    value={newToolName}
                                    onChange={(e) => setNewToolName(e.target.value)}
                                    placeholder="e.g. text_analyzer"
                                    style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid #e5e7eb', fontSize: '14px', outline: 'none' }}
                                />
                                <div style={{ fontSize: '11px', marginTop: '4px', color: /^[a-z_][a-z0-9_]*$/.test(newToolName) ? '#10b981' : '#ef4444' }}>
                                    {newToolName && !/^[a-z_][a-z0-9_]*$/.test(newToolName) && "Name must be valid python function (lowercase, underscores, no spaces)"}
                                </div>
                            </div>
                            <div>
                                <label style={{ display: 'block', fontSize: '12px', fontWeight: 700, color: '#4b5563', marginBottom: '8px', textTransform: 'uppercase' }}>Description</label>
                                <textarea
                                    value={newToolDescription}
                                    onChange={(e) => setNewToolDescription(e.target.value)}
                                    placeholder="What does this tool do?"
                                    style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid #e5e7eb', fontSize: '14px', outline: 'none', minHeight: '100px', resize: 'vertical' }}
                                />
                            </div>
                            <div style={{ display: 'flex', gap: '12px', marginTop: '12px' }}>
                                <button
                                    onClick={() => setIsCreateModalOpen(false)}
                                    style={{ flex: 1, height: '48px', borderRadius: '8px', border: '1px solid #e5e7eb', background: 'white', color: '#4b5563', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }}
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleCreateTool}
                                    disabled={!newToolName || !newToolDescription || !/^[a-z_][a-z0-9_]*$/.test(newToolName)}
                                    style={{ flex: 1, height: '48px', borderRadius: '8px', border: 'none', background: '#111827', color: 'white', fontSize: '14px', fontWeight: 700, cursor: 'pointer', opacity: (!newToolName || !newToolDescription || !/^[a-z_][a-z0-9_]*$/.test(newToolName)) ? 0.5 : 1 }}
                                >
                                    Create Tool
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            <DeleteToolModal
                isOpen={isDeleteModalOpen}
                tool={selectedTool}
                onConfirm={handleDeleteTool}
                onClose={() => setIsDeleteModalOpen(false)}
            />
        </div>
    );
}

const DeleteToolModal = ({ isOpen, tool, onConfirm, onClose }) => {
    if (!isOpen) return null;
    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(4px)' }}>
            <div style={{ background: 'white', padding: '32px', borderRadius: '16px', maxWidth: '400px', width: '90%', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', border: '1px solid #e5e7eb' }}>
                <div style={{ padding: '12px', borderRadius: '50%', background: '#fef2f2', width: 'fit-content', margin: '0 auto 16px' }}>
                    <Trash2 size={32} color="#ef4444" />
                </div>
                <h3 style={{ margin: '0 0 8px 0', fontSize: '20px', fontWeight: 800, color: '#111827', textAlign: 'center' }}>Delete Tool?</h3>
                <p style={{ margin: '0 0 24px 0', fontSize: '14px', color: '#6b7280', textAlign: 'center' }}>
                    Are you sure you want to delete <strong>{tool?.name}</strong>? This will permanently remove the tool file.
                </p>
                <div style={{ display: 'flex', gap: '12px' }}>
                    <button
                        onClick={onClose}
                        style={{ flex: 1, padding: '10px', borderRadius: '8px', border: '1px solid #e5e7eb', background: 'white', color: '#4b5563', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }}
                    >
                        Cancel
                    </button>
                    <button
                        onClick={onConfirm}
                        style={{ flex: 1, padding: '10px', borderRadius: '8px', border: 'none', background: '#ef4444', color: 'white', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }}
                    >
                        Delete
                    </button>
                </div>
            </div>
        </div>
    );
};
