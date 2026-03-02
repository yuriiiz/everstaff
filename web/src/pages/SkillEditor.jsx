import { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import { Save, ArrowLeft, FileText, File, Folder, Plus, Trash2, ChevronRight, ChevronDown, Loader2, CheckCircle } from 'lucide-react';
import LoadingView from '../components/LoadingView';

const editorStyles = `
    .file-item:hover .delete-btn { opacity: 1 !important; }
    .file-item:hover { background: #f1f5f9; }
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    .animate-spin { animation: spin 1s linear infinite; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    .fade-in { animation: fadeIn 0.3s ease-out forwards; }
    .glass-modal { background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.3); }
`;

// Helper for safe URL paths - encodes everything except slashes
const securePath = (path) => path.split('/').map(encodeURIComponent).join('/');

function CustomModal({ isOpen, title, children, onConfirm, onCancel, confirmText = "Confirm", cancelText = "Cancel", type = "info" }) {
    if (!isOpen) return null;
    return (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(4px)' }}>
            <div className="glass-modal fade-in" style={{ width: '90%', maxWidth: '440px', background: 'white', borderRadius: '20px', padding: '32px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)' }}>
                <h3 style={{ fontSize: '20px', fontWeight: 800, margin: '0 0 12px 0', color: '#111827' }}>{title}</h3>
                <div style={{ color: '#4b5563', fontSize: '15px', lineHeight: '1.6', marginBottom: '32px' }}>{children}</div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                    <button className="btn" onClick={onCancel} style={{ padding: '0 20px', height: '44px', fontWeight: 600 }}>{cancelText}</button>
                    <button className={`btn ${type === 'danger' ? '' : 'btn-primary'}`}
                        style={type === 'danger' ? { background: '#ef4444', color: 'white', padding: '0 20px', height: '44px', fontWeight: 600 } : { padding: '0 20px', height: '44px', fontWeight: 600 }}
                        onClick={onConfirm}>
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>
    );
}

function Toast({ message, type = "success", onFadeOut }) {
    useEffect(() => {
        const timer = setTimeout(onFadeOut, 3000);
        return () => clearTimeout(timer);
    }, [onFadeOut]);

    return (
        <div className="fade-in" style={{
            position: 'fixed', bottom: '32px', right: '32px', zIndex: 2000,
            background: type === 'error' ? '#ef4444' : '#111827',
            color: 'white', padding: '12px 24px', borderRadius: '12px',
            boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)',
            display: 'flex', alignItems: 'center', gap: '12px', fontSize: '14px', fontWeight: 600
        }}>
            {type === 'success' ? <CheckCircle size={18} /> : <Trash2 size={18} />}
            {message}
        </div>
    );
}

function buildTree(files) {
    const root = {};
    files.forEach(file => {
        const parts = file.path.split('/');
        let node = root;
        parts.forEach((part, i) => {
            if (i === parts.length - 1) {
                node[part] = null; // leaf
            } else {
                if (!node[part] || node[part] === null) node[part] = {};
                node = node[part];
            }
        });
    });
    return root;
}

function FileTree({ tree, files, selectedFile, onSelect, onDelete, onAdd, parentPath = '' }) {
    const entries = Object.entries(tree).sort(([aName, aNode], [bName, bNode]) => {
        // Folders first
        if (aNode !== null && bNode === null) return -1;
        if (aNode === null && bNode !== null) return 1;
        return aName.localeCompare(bName);
    });

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {entries.map(([name, node]) => {
                const fullPath = parentPath ? `${parentPath}/${name}` : name;
                const isLeaf = node === null;

                if (!isLeaf) {
                    return (
                        <div key={fullPath}>
                            <div style={{
                                display: 'flex', alignItems: 'center', gap: '6px',
                                padding: '6px 8px', fontSize: '13px',
                                color: '#64748b', fontWeight: 600
                            }}>
                                <Folder size={14} /> {name}
                            </div>
                            <div style={{ paddingLeft: '16px', borderLeft: '1px solid #e2e8f0', marginLeft: '14px' }}>
                                <FileTree
                                    tree={node}
                                    files={files}
                                    selectedFile={selectedFile}
                                    onSelect={onSelect}
                                    onDelete={onDelete}
                                    onAdd={onAdd}
                                    parentPath={fullPath}
                                />
                            </div>
                        </div>
                    );
                }

                const fileObj = files.find(f => f.path === fullPath) || { path: fullPath, name };
                const isSelected = selectedFile?.path === fullPath;
                return (
                    <div
                        key={fullPath}
                        className="file-item"
                        onClick={() => onSelect(fileObj)}
                        style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            padding: '6px 10px', borderRadius: '6px',
                            fontSize: '13px', cursor: 'pointer',
                            background: isSelected ? '#111827' : 'transparent',
                            color: isSelected ? 'white' : '#4b5563',
                            fontWeight: isSelected ? 600 : 500,
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {name.endsWith('.md') ? <FileText size={14} /> : <File size={14} />}
                            <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{name}</span>
                        </div>
                        {name !== 'SKILL.md' && (
                            <button
                                onClick={(e) => { e.stopPropagation(); onDelete(fileObj); }}
                                style={{
                                    background: 'transparent', border: 'none', padding: '2px',
                                    color: isSelected ? 'rgba(255,255,255,0.6)' : '#9ca3af',
                                    cursor: 'pointer', opacity: 0, transition: 'opacity 0.2s'
                                }}
                                className="delete-btn"
                            >
                                <Trash2 size={12} />
                            </button>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

export default function SkillEditor() {
    const { skillName } = useParams();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();

    const [files, setFiles] = useState([]);
    const [tree, setTree] = useState({});
    const [selectedFile, setSelectedFile] = useState(null);
    const [code, setCode] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [isDirty, setIsDirty] = useState(false);

    // UI State
    const [toast, setToast] = useState(null);
    const [modal, setModal] = useState({ isOpen: false, type: 'info', title: '', message: '', targetFile: null });
    const [promptValue, setPromptValue] = useState('');

    const refreshFiles = async (selectPath = null) => {
        try {
            const res = await fetch(`/api/skills/${skillName}/files`);
            const data = await res.json();
            const fileList = data.files || [];
            setFiles(fileList);
            setTree(buildTree(fileList));

            if (selectPath) {
                const found = fileList.find(f => f.path === selectPath);
                if (found) {
                    setSearchParams({ file: found.path }, { replace: true });
                    await loadContent(found);
                }
            } else if (!selectedFile) {
                const urlFile = searchParams.get('file');
                let found = urlFile ? fileList.find(f => f.path === urlFile) : null;
                if (!found && fileList.length > 0) {
                    found = fileList.find(f => f.name === 'SKILL.md') || fileList[0];
                }
                if (found) {
                    setSearchParams({ file: found.path }, { replace: true });
                    await loadContent(found);
                }
            }
        } catch (err) {
            console.error("Failed to load files", err);
        }
    };

    useEffect(() => {
        refreshFiles().then(() => setLoading(false));
    }, [skillName]);

    // Handle Ctrl+S / Cmd+S
    useEffect(() => {
        const handleKeyDown = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                if (isDirty) handleSave();
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [isDirty, selectedFile, code, skillName]);

    const handleSelectFile = async (file, force = false) => {
        if (!force && isDirty) {
            setModal({
                isOpen: true,
                type: 'discard',
                title: "Discard Changes?",
                message: "You have unsaved changes in the current file. Are you sure you want to switch files?",
                targetFile: file
            });
            return;
        }
        setSearchParams({ file: file.path }, { replace: true });
        await loadContent(file);
    };

    const loadContent = async (file) => {
        setSelectedFile(file);
        try {
            const res = await fetch(`/api/skills/${skillName}/files/${securePath(file.path)}`);
            const data = await res.json();
            setCode(data.content || '');
            setIsDirty(false);
        } catch (err) {
            setToast({ message: "Failed to load file content", type: "error" });
        }
    };

    const handleSave = async () => {
        if (!selectedFile) return;
        setSaving(true);
        try {
            const res = await fetch(`/api/skills/${skillName}/files/${securePath(selectedFile.path)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: code })
            });
            if (res.ok) {
                setIsDirty(false);
                setToast({ message: "Saved successfully!", type: "success" });
            } else {
                const data = await res.json();
                setToast({ message: "Failed to save: " + (data.detail || "Unknown error"), type: "error" });
            }
        } catch (err) {
            setToast({ message: "Save error: " + err.message, type: "error" });
        } finally {
            setSaving(false);
        }
    };

    const handleAddFile = () => {
        setPromptValue('');
        setModal({ isOpen: true, type: 'add', title: "Create New File" });
    };

    const confirmAddFile = async () => {
        const path = promptValue.trim();
        if (!path) return;
        setModal({ ...modal, isOpen: false });
        try {
            const res = await fetch(`/api/skills/${skillName}/files`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path })
            });
            if (res.ok) {
                await refreshFiles(path);
                setToast({ message: `File ${path} created`, type: "success" });
            } else {
                const data = await res.json();
                setToast({ message: "Error: " + (data.detail || "Failed to create file"), type: "error" });
            }
        } catch (err) {
            setToast({ message: "Error: " + err.message, type: "error" });
        }
    };

    const handleDeleteFile = (file) => {
        setModal({
            isOpen: true,
            type: 'delete',
            title: "Delete File?",
            message: `Are you sure you want to delete "${file.path}"? This action cannot be undone.`,
            targetFile: file
        });
    };

    const confirmDeleteFile = async () => {
        const file = modal.targetFile;
        setModal({ ...modal, isOpen: false });
        if (!file) return;
        try {
            const res = await fetch(`/api/skills/${skillName}/files/${securePath(file.path)}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                if (selectedFile?.path === file.path) {
                    setSelectedFile(null);
                    setCode('');
                }
                await refreshFiles();
                setToast({ message: "File deleted", type: "success" });
            } else {
                const data = await res.json();
                setToast({ message: "Delete failed: " + (data.detail || "Unknown error"), type: "error" });
            }
        } catch (err) {
            setToast({ message: "Delete error: " + err.message, type: "error" });
        }
    };

    const handleModalConfirm = () => {
        if (modal.type === 'delete') {
            confirmDeleteFile();
        } else if (modal.type === 'add') {
            confirmAddFile();
        } else if (modal.type === 'discard') {
            setModal({ ...modal, isOpen: false });
            setIsDirty(false);
            if (modal.targetFile) {
                setSearchParams({ file: modal.targetFile.path }, { replace: true });
                loadContent(modal.targetFile);
            }
        }
    };

    const getLanguage = (filename) => {
        if (!filename) return 'text';
        if (filename.endsWith('.py')) return 'python';
        if (filename.endsWith('.md')) return 'markdown';
        if (filename.endsWith('.json')) return 'json';
        if (filename.endsWith('.js') || filename.endsWith('.jsx')) return 'javascript';
        if (filename.endsWith('.html')) return 'html';
        if (filename.endsWith('.yaml') || filename.endsWith('.yml')) return 'yaml';
        return 'text';
    };

    if (loading) return <LoadingView message="Initializing Skill Editor..." />;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#f9fafb' }}>
            <style>{editorStyles}</style>

            {/* Custom UI Elements */}
            <CustomModal
                isOpen={modal.isOpen}
                title={modal.title}
                onConfirm={handleModalConfirm}
                onCancel={() => setModal({ ...modal, isOpen: false })}
                confirmText={modal.type === 'delete' ? 'Delete Permanently' : (modal.type === 'add' ? 'Create File' : 'Discard and Switch')}
                type={modal.type === 'delete' ? 'danger' : 'info'}
            >
                {modal.type === 'add' ? (
                    <div>
                        <p style={{ marginBottom: '12px' }}>Enter the relative path for the new file (e.g., <code style={{ color: '#e11d48' }}>scripts/custom.py</code>):</p>
                        <input
                            autoFocus
                            style={{ width: '100%', height: '44px', border: '2px solid #e5e7eb', borderRadius: '10px', padding: '0 16px', outline: 'none', transition: 'border-color 0.2s', boxSizing: 'border-box' }}
                            value={promptValue}
                            onChange={(e) => setPromptValue(e.target.value)}
                            placeholder="filename.ext"
                            onKeyDown={(e) => e.key === 'Enter' && handleModalConfirm()}
                        />
                    </div>
                ) : (
                    <p>{modal.message}</p>
                )}
            </CustomModal>

            {toast && <Toast {...toast} onFadeOut={() => setToast(null)} />}

            {/* Header */}
            <div style={{
                height: '60px', background: 'white', borderBottom: '1px solid #e5e7eb',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <button onClick={() => navigate('/skills')} className="btn" style={{ padding: '6px' }}>
                        <ArrowLeft size={18} />
                    </button>
                    <div>
                        <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Skill Editor</div>
                        <h1 style={{ fontSize: '16px', fontWeight: 700, color: '#111827', margin: 0 }}>{skillName}</h1>
                    </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    {isDirty && <span style={{ fontSize: '12px', color: '#6b7280', fontWeight: 500 }}>Unsaved changes</span>}
                    <button
                        onClick={handleSave}
                        className="btn btn-primary"
                        disabled={saving || !isDirty}
                        style={{ height: '36px', padding: '0 16px', gap: '8px', minWidth: '100px', display: 'flex', justifyContent: 'center' }}
                    >
                        {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        Save
                    </button>
                </div>
            </div>

            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                {/* Sidebar */}
                <div style={{
                    width: '260px', background: 'white', borderRight: '1px solid #e5e7eb',
                    display: 'flex', flexDirection: 'column', overflow: 'hidden'
                }}>
                    <div style={{
                        padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        borderBottom: '1px solid #f3f4f6'
                    }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#475569', textTransform: 'uppercase' }}>Files</span>
                        <button onClick={handleAddFile} className="btn" style={{ padding: '4px' }} title="New File">
                            <Plus size={14} />
                        </button>
                    </div>
                    <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
                        <FileTree
                            tree={tree}
                            files={files}
                            selectedFile={selectedFile}
                            onSelect={handleSelectFile}
                            onDelete={handleDeleteFile}
                            onAdd={handleAddFile}
                        />
                    </div>
                </div>

                {/* Editor Area */}
                <div style={{ flex: 1, background: 'white', display: 'flex', flexDirection: 'column' }}>
                    {selectedFile ? (
                        <>
                            <div style={{
                                padding: '8px 20px', background: '#f8fafc', borderBottom: '1px solid #e5e7eb',
                                display: 'flex', alignItems: 'center', gap: '8px', color: '#64748b', fontSize: '13px'
                            }}>
                                <FileText size={14} />
                                <span style={{ fontWeight: 500 }}>{selectedFile.path}</span>
                            </div>
                            <div style={{ flex: 1, overflow: 'hidden' }}>
                                <Editor
                                    height="100%"
                                    theme="light"
                                    key={`${skillName}-${selectedFile.path}`}
                                    language={getLanguage(selectedFile.name)}
                                    value={code}
                                    onChange={(val) => { setCode(val); setIsDirty(true); }}
                                    options={{
                                        minimap: { enabled: false },
                                        fontSize: 14,
                                        fontFamily: 'Menlo, Monaco, Consolas, "Courier New", monospace',
                                        lineNumbers: 'on',
                                        renderWhitespace: 'none',
                                        scrollBeyondLastLine: false,
                                        automaticLayout: true,
                                        padding: { top: 16 }
                                    }}
                                />
                            </div>
                        </>
                    ) : (
                        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>
                            <File size={48} style={{ marginBottom: '16px', opacity: 0.2 }} />
                            <p>Select a file to edit</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
