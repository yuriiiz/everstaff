import React, { useState, useEffect } from 'react';
import { Folder, File, ChevronRight, FileText, Image, Film, Globe, Download, Link, Eye, RefreshCw, ChevronLeft, Check } from 'lucide-react';

const ICON_MAP = {
    'text/': FileText,
    'image/': Image,
    'video/': Film,
    'text/html': Globe,
    'application/pdf': FileText,
};

function getFileIcon(mimeType, isDirectory) {
    if (isDirectory) return Folder;
    if (ICON_MAP[mimeType]) return ICON_MAP[mimeType];
    for (const [prefix, Icon] of Object.entries(ICON_MAP)) {
        if (mimeType.startsWith(prefix)) return Icon;
    }
    return File;
}

function formatSize(bytes) {
    if (!bytes) return '--';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateStr) {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function guessMimeClient(filename) {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    const map = {
        md: 'text/markdown', txt: 'text/plain', py: 'text/x-python',
        js: 'text/javascript', ts: 'text/typescript', json: 'application/json',
        yaml: 'application/x-yaml', yml: 'application/x-yaml',
        html: 'text/html', css: 'text/css', csv: 'text/csv',
        png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
        gif: 'image/gif', svg: 'image/svg+xml', pdf: 'application/pdf',
        mp4: 'video/mp4', webm: 'video/webm', mp3: 'audio/mpeg',
        xml: 'text/xml', sh: 'text/x-shellscript', bash: 'text/x-shellscript',
        rs: 'text/x-rust', go: 'text/x-go', java: 'text/x-java',
        rb: 'text/x-ruby', php: 'text/x-php', sql: 'text/x-sql',
    };
    return map[ext] || 'application/octet-stream';
}

export default function FileBrowser({ sessionId, onPreview, refreshTrigger }) {
    const [path, setPath] = useState('');
    const [files, setFiles] = useState([]);
    const [loading, setLoading] = useState(true);
    const [isInitialLoad, setIsInitialLoad] = useState(true);
    const [error, setError] = useState(null);
    const [copiedPath, setCopiedPath] = useState(null);

    const fetchFiles = (targetPath = path) => {
        setLoading(true);
        setError(null);
        fetch(`/api/sessions/${sessionId}/files?path=${encodeURIComponent(targetPath)}`)
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                setFiles(data.files || []);
                setPath(data.path || '');
                setLoading(false);
                setIsInitialLoad(false);
            })
            .catch(err => {
                setError(err.message);
                setLoading(false);
                setIsInitialLoad(false);
            });
    };

    useEffect(() => {
        if (sessionId) {
            // Only reset files and initial load flag when the session specifically changes
            setFiles([]);
            setIsInitialLoad(true);
            fetchFiles('');
        }
    }, [sessionId]);

    // Independent effect for refreshTrigger to fetch without resetting UI
    useEffect(() => {
        if (sessionId && !isInitialLoad) {
            fetchFiles();
        }
    }, [refreshTrigger]);

    const navigateTo = (newPath) => {
        fetchFiles(newPath);
    };

    const handleBack = () => {
        const parts = path.split('/').filter(Boolean);
        parts.pop();
        navigateTo(parts.join('/'));
    };

    const handleFileClick = (file) => {
        if (file.type === 'directory') {
            const newPath = path ? `${path}/${file.name}` : file.name;
            navigateTo(newPath);
        } else {
            const filePath = path ? `${path}/${file.name}` : file.name;
            onPreview({
                file_path: filePath,
                file_name: file.name,
                size: file.size,
                mime_type: guessMimeClient(file.name)
            });
        }
    };

    const handleDownload = (e, file) => {
        e.stopPropagation();
        const filePath = path ? `${path}/${file.name}` : file.name;
        const url = `/api/sessions/${sessionId}/files/${encodeURIComponent(filePath)}?download=true`;
        const a = document.createElement('a');
        a.href = url;
        a.download = file.name;
        a.click();
    };

    const handleCopyLink = async (e, file) => {
        e.stopPropagation();
        const filePath = path ? `${path}/${file.name}` : file.name;
        const url = `${window.location.origin}/api/sessions/${sessionId}/files/${encodeURIComponent(filePath)}`;
        try {
            await navigator.clipboard.writeText(url);
            setCopiedPath(filePath);
            setTimeout(() => setCopiedPath(null), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    const breadcrumbs = path.split('/').filter(Boolean);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'white', borderRadius: '8px', border: '1px solid #e5e7eb', overflow: 'hidden' }}>
            <div style={{
                padding: '12px 16px',
                borderBottom: '1px solid #e5e7eb',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: '#f9fafb',
                flexShrink: 0
            }}>
                <button
                    onClick={() => navigateTo('')}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', display: 'flex', color: '#6b7280' }}
                    title="Home"
                >
                    <Folder size={16} />
                </button>
                {path && (
                    <button
                        onClick={handleBack}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', display: 'flex', color: '#6b7280' }}
                        title="Back"
                    >
                        <ChevronLeft size={16} />
                    </button>
                )}
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '4px', overflow: 'hidden', fontSize: '12px', color: '#4b5563', fontWeight: 500 }}>
                    {!path && <span style={{ opacity: 0.6 }}>Workspace Root</span>}
                    {breadcrumbs.map((crumb, idx) => (
                        <React.Fragment key={idx}>
                            <ChevronRight size={12} style={{ color: '#9ca3af' }} />
                            <span
                                style={{
                                    cursor: 'pointer',
                                    maxWidth: '120px',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap'
                                }}
                                onClick={() => navigateTo(breadcrumbs.slice(0, idx + 1).join('/'))}
                            >
                                {crumb}
                            </span>
                        </React.Fragment>
                    ))}
                </div>
                <button
                    onClick={() => fetchFiles()}
                    disabled={loading}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', display: 'flex', color: '#6b7280' }}
                    title="Refresh"
                >
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto' }}>
                {loading && isInitialLoad && files.length === 0 ? (
                    <div style={{ padding: '40px', textAlign: 'center', color: '#9ca3af', fontSize: '13px' }}>Loading files...</div>
                ) : error && files.length === 0 ? (
                    <div style={{ padding: '40px', textAlign: 'center', color: '#ef4444', fontSize: '13px' }}>Error: {error}</div>
                ) : files.length === 0 && !loading ? (
                    <div style={{ padding: '40px', textAlign: 'center', color: '#9ca3af', fontSize: '13px' }}>No files in this directory</div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                        {files.map((file, idx) => {
                            const isDir = file.type === 'directory';
                            const mime = isDir ? '' : guessMimeClient(file.name);
                            const Icon = getFileIcon(mime, isDir);
                            return (
                                <div
                                    key={idx}
                                    onClick={() => handleFileClick(file)}
                                    className={`${(Date.now() - new Date(file.modified_at).getTime() < 30000) ? 'file-row-new' : ''}`}
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        padding: '10px 16px',
                                        borderBottom: '1px solid #f3f4f6',
                                        cursor: 'pointer',
                                        transition: 'background 0.1s',
                                        gap: '12px',
                                        minWidth: 0
                                    }}
                                    onMouseEnter={e => e.currentTarget.style.background = '#f9fafb'}
                                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                >
                                    <Icon size={16} style={{ color: isDir ? '#3b82f6' : '#64748b', flexShrink: 0 }} />
                                    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                        <div style={{
                                            fontSize: '12px',
                                            fontWeight: isDir ? 600 : 500,
                                            color: '#1f2937',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '6px',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap'
                                        }}>
                                            {file.name}
                                            {(Date.now() - new Date(file.modified_at).getTime() < 30000) && (
                                                <span className="new-badge">New</span>
                                            )}
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '10px', color: '#9ca3af' }}>
                                            <span>{isDir ? 'Folder' : formatSize(file.size)}</span>
                                            <span>•</span>
                                            <span>{formatDate(file.modified_at)}</span>
                                        </div>
                                    </div>
                                    {!isDir && (
                                        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                                            <button
                                                onClick={(e) => handleCopyLink(e, file)}
                                                title="Copy link"
                                                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: copiedPath === (path ? `${path}/${file.name}` : file.name) ? '#10b981' : '#9ca3af', display: 'flex' }}
                                            >
                                                {copiedPath === (path ? `${path}/${file.name}` : file.name) ? <Check size={14} /> : <Link size={14} />}
                                            </button>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleDownload(e, file); }}
                                                title="Download"
                                                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: '#9ca3af', display: 'flex' }}
                                            >
                                                <Download size={14} />
                                            </button>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
            <style>{`
                .animate-spin {
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    );
}
