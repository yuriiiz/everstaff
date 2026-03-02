import { useState, useEffect } from 'react';
import { Download, Search, FileText, CheckCircle, ExternalLink, Package, File, Folder, ChevronRight, ChevronDown, List, Zap, Plus, Edit } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useSearchParams, useNavigate } from 'react-router-dom';

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

function FileTree({ files, selectedFile, onSelect }) {
    const tree = buildTree(files);

    function renderNode(node, name, parentPath) {
        const fullPath = parentPath ? `${parentPath}/${name}` : name;
        const isLeaf = node === null;

        if (!isLeaf) {
            const children = Object.entries(node);
            return (
                <div key={fullPath}>
                    <div style={{
                        display: 'flex', alignItems: 'center', gap: '6px',
                        padding: '4px 8px', fontSize: '12px',
                        color: '#64748b', fontWeight: 600
                    }}>
                        <Folder size={13} /> {name}
                    </div>
                    <div style={{ paddingLeft: '12px' }}>
                        {children.map(([childName, childNode]) => renderNode(childNode, childName, fullPath))}
                    </div>
                </div>
            );
        }

        const fileObj = files.find(f => f.path === fullPath) || { path: fullPath, name };
        const isSelected = selectedFile?.path === fullPath;
        return (
            <div
                key={fullPath}
                onClick={() => onSelect(fileObj)}
                style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    padding: '6px 10px', borderRadius: '6px',
                    fontSize: '12px', cursor: 'pointer',
                    background: isSelected ? '#111827' : 'transparent',
                    color: isSelected ? 'white' : '#4b5563',
                    fontWeight: isSelected ? 600 : 500,
                }}
            >
                {name.endsWith('.md') ? <FileText size={13} /> : <File size={13} />}
                {name}
            </div>
        );
    }

    return (
        <div>
            {Object.entries(tree).map(([name, node]) => renderNode(node, name, ''))}
        </div>
    );
}

export default function SkillStore() {
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = searchParams.get('tab') || 'installed';
    const setActiveTab = (tab) => setSearchParams({ tab });
    const [skills, setSkills] = useState([]);
    const [selectedSkill, setSelectedSkill] = useState(null);
    const [skillFiles, setSkillFiles] = useState([]);
    const [selectedFile, setSelectedFile] = useState(null);
    const [fileContent, setFileContent] = useState('');
    const [marketQuery, setMarketQuery] = useState('');
    const [marketResults, setMarketResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [installingPkg, setInstallingPkg] = useState(null);
    const [installResult, setInstallResult] = useState(null);
    const [showModal, setShowModal] = useState(false);

    useEffect(() => {
        fetch('/api/skills')
            .then(res => res.json())
            .then(data => {
                setSkills(data);
                if (data.length > 0) handleSelectSkill(data[0]);
            });

        // Fetch popular skills initially
        fetch('/api/skills/store')
            .then(res => res.json())
            .then(data => setMarketResults(Array.isArray(data) ? data : []));
    }, []);

    const handleSelectSkill = (skill) => {
        setSelectedSkill(skill);
        setFileContent('');
        setSelectedFile(null);

        // Fetch files for tree
        fetch(`/api/skills/${skill.name}/files`)
            .then(res => res.json())
            .then(data => {
                const files = data.files || [];
                setSkillFiles(files);

                // Default to SKILL.md content
                const skillMd = files.find(f => f.name === 'SKILL.md');
                if (skillMd) {
                    setSelectedFile(skillMd);
                    handleSelectFile(skillMd, skill.name);
                }
            });
    };

    const handleSelectFile = (file, skillNameOverride) => {
        const skillName = skillNameOverride || selectedSkill?.name;
        if (!skillName) return;

        setSelectedFile(file);
        fetch(`/api/skills/${skillName}/files/${file.path}`)
            .then(res => res.json())
            .then(data => {
                if (data.content) setFileContent(data.content);
                else setFileContent('```\n' + (data.error || 'Failed to load file content') + '\n```');
            });
    };

    const searchMarket = () => {
        setIsSearching(true);
        fetch(`/api/skills/store?query=${marketQuery}`)
            .then(res => res.json())
            .then(data => {
                setMarketResults(Array.isArray(data) ? data : []);
                setIsSearching(false);
            })
            .catch(err => {
                console.error('Search failed:', err);
                setIsSearching(false);
            });
    };

    const installSkill = (pkg) => {
        setInstallingPkg(pkg);
        setInstallResult(null);
        setShowModal(true);

        fetch('/api/skills/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: pkg })
        }).then(async res => {
            const data = await res.json();
            setInstallResult({
                success: res.ok,
                message: data.message || (res.ok ? 'Successfully installed' : 'Installation failed'),
                output: data.output || ''
            });
            if (res.ok) {
                // Refresh installed list
                fetch('/api/skills')
                    .then(res => res.json())
                    .then(setSkills);
            }
            setInstallingPkg(null);
        }).catch(err => {
            setInstallResult({
                success: false,
                message: 'Network error or server unavailable',
                output: err.message
            });
            setInstallingPkg(null);
        });
    };

    const InstallationModal = () => {
        if (!showModal) return null;
        return (
            <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(4px)' }}>
                <div style={{ background: 'white', padding: '32px', borderRadius: '16px', maxWidth: '600px', width: '90%', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)' }}>
                    <div style={{ textAlign: 'center', marginBottom: '24px' }}>
                        <div style={{ width: '64px', height: '64px', borderRadius: '50%', background: installResult ? (installResult.success ? '#ecfdf5' : '#fef2f2') : '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                            {installResult ? (
                                installResult.success ? <CheckCircle size={32} color="#10b981" /> : <Package size={32} color="#ef4444" />
                            ) : (
                                <div style={{ width: '32px', height: '32px', border: '3px solid #e5e7eb', borderTopColor: '#111827', borderRadius: '50%', animation: 'spin 1s linear infinite' }}></div>
                            )}
                        </div>
                        <h3 style={{ fontSize: '20px', fontWeight: 800, color: '#111827', margin: '0 0 8px 0' }}>
                            {installingPkg ? `Installing ${installingPkg}...` : (installResult?.success ? 'Installation Complete' : 'Installation Failed')}
                        </h3>
                        <p style={{ fontSize: '14px', color: '#6b7280', margin: 0 }}>
                            {installResult ? installResult.message : 'Please wait while we set up the skill for you.'}
                        </p>
                    </div>

                    {installResult?.output && (
                        <div style={{ background: '#0f172a', padding: '16px', borderRadius: '12px', marginBottom: '24px', maxHeight: '240px', overflow: 'auto' }}>
                            <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.05em' }}>Terminal Output</div>
                            <pre style={{ margin: 0, fontSize: '12px', color: '#e2e8f0', whiteSpace: 'pre-wrap', fontFamily: 'Menlo, Monaco, Consolas, monospace' }}>
                                {installResult.output}
                            </pre>
                        </div>
                    )}

                    <button
                        className="btn btn-primary"
                        style={{ width: '100%', height: '48px', justifyContent: 'center', background: installResult?.success ? '#10b981' : '#111827', fontSize: '15px', fontWeight: 600 }}
                        onClick={() => setShowModal(false)}
                        disabled={!installResult}
                    >
                        Close
                    </button>
                    <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
                </div>
            </div>
        );
    };

    const handleCreate = () => {
        navigate('/sessions?agent_uuid=builtin_skill_creator');
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#f9fafb' }}>
            <div style={{ padding: '0 24px', background: 'white', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', height: '60px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <h1 style={{ fontSize: '15px', fontWeight: 700, color: '#111827', margin: 0 }}>Skills</h1>
                    {activeTab === 'installed' && (
                        <button
                            className="btn"
                            style={{ padding: '4px 8px' }}
                            onClick={handleCreate}
                            title="Add Skill"
                        >
                            <Plus size={16} />
                        </button>
                    )}
                </div>
                <div style={{ display: 'flex', background: '#f3f4f6', padding: '2px', borderRadius: '8px', border: '1px solid #e5e7eb', gap: '2px' }}>
                    {['installed', 'market'].map(tab => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            style={{
                                padding: '6px 14px', borderRadius: '6px', fontSize: '13px', fontWeight: 600, transition: 'all 0.2s',
                                display: 'flex', alignItems: 'center', gap: '8px',
                                background: activeTab === tab ? 'white' : 'transparent',
                                color: activeTab === tab ? '#111827' : '#6b7280',
                                boxShadow: activeTab === tab ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                                border: 'none', cursor: 'pointer'
                            }}
                        >
                            {tab === 'installed' ? <><CheckCircle size={14} /> Installed</> : <><Package size={14} /> Marketplace</>}
                        </button>
                    ))}
                </div>
            </div>

            <div style={{ flex: 1, overflow: 'hidden' }}>
                {activeTab === 'installed' ? (
                    <div style={{ display: 'flex', height: '100%' }}>
                        {/* 1. Skills List */}
                        <div style={{ width: '300px', borderRight: '1px solid #e5e7eb', background: 'white', overflowY: 'auto' }}>
                            {skills.map(s => (
                                <div
                                    key={s.name}
                                    onClick={() => handleSelectSkill(s)}
                                    style={{
                                        padding: '16px 20px', borderBottom: '1px solid #f3f4f6', cursor: 'pointer', transition: 'all 0.2s',
                                        background: selectedSkill?.name === s.name ? '#f8fafc' : 'white',
                                        borderLeft: selectedSkill?.name === s.name ? '4px solid #111827' : '4px solid transparent',
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        gap: '12px'
                                    }}
                                >
                                    <Zap size={16} style={{ marginTop: '2px', color: selectedSkill?.name === s.name ? '#111827' : '#9ca3af' }} />
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 700, fontSize: '14px', color: '#111827', marginBottom: '4px' }}>{s.name}</div>
                                        <div style={{ fontSize: '12px', color: '#6b7280', lineHeight: '1.4', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                                            {s.description && s.description !== '---' ? s.description : 'No description provided'}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>

                        {/* 2. Content View (Markdown Rendering) */}
                        <div style={{ flex: 1, background: 'white', overflowY: 'auto', padding: '40px', position: 'relative' }}>
                            <div className="prose" style={{ maxWidth: '800px', margin: '0 auto' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#6b7280', fontSize: '13px', marginBottom: '24px' }}>
                                    <FileText size={14} />
                                    <span>{selectedFile ? selectedFile.path : 'SKILL.md'}</span>
                                </div>

                                {(() => {
                                    // Basic Frontmatter Parser
                                    const fmMatch = fileContent.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
                                    let metadata = null;
                                    let body = fileContent;

                                    if (fmMatch) {
                                        const fmLines = fmMatch[1].split('\n');
                                        metadata = {};
                                        fmLines.forEach(line => {
                                            const [key, ...val] = line.split(':');
                                            if (key && val.length > 0) {
                                                metadata[key.trim().toLowerCase()] = val.join(':').trim();
                                            }
                                        });
                                        body = fmMatch[2];
                                    }

                                    return (
                                        <>
                                            {metadata && (
                                                <div style={{
                                                    background: 'white',
                                                    border: '1px solid #e5e7eb',
                                                    borderRadius: '12px',
                                                    padding: '32px',
                                                    marginBottom: '40px',
                                                    boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
                                                }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                            <Package size={16} color="#6b7280" />
                                                            <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: '#6b7280' }}>Skill Specification</span>
                                                        </div>
                                                        <button
                                                            className="btn btn-secondary"
                                                            style={{ height: '32px', padding: '0 12px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
                                                            onClick={(e) => { e.stopPropagation(); navigate(`/skills/edit/${selectedSkill?.name}`); }}
                                                        >
                                                            <Edit size={14} /> Edit Skill
                                                        </button>
                                                    </div>
                                                    <h1 style={{ fontSize: '24px', fontWeight: 800, margin: '0 0 12px 0', letterSpacing: '-0.025em', color: '#111827' }}>
                                                        {metadata.name || selectedSkill?.name}
                                                    </h1>
                                                    <p style={{ fontSize: '15px', lineHeight: '1.6', color: '#4b5563', margin: 0 }}>
                                                        {metadata.description || selectedSkill?.description}
                                                    </p>
                                                </div>
                                            )}
                                            <ReactMarkdown
                                                remarkPlugins={[remarkGfm]}
                                                components={{
                                                    table: ({ node, ...props }) => <table style={{ borderCollapse: 'collapse', width: '100%', marginBottom: '16px', fontSize: '15px' }} {...props} />,
                                                    th: ({ node, ...props }) => <th style={{ border: '1px solid #e5e7eb', padding: '8px 12px', background: '#f9fafb', fontWeight: 600, textAlign: 'left' }} {...props} />,
                                                    td: ({ node, ...props }) => <td style={{ border: '1px solid #e5e7eb', padding: '8px 12px' }} {...props} />,
                                                    h1: ({ node, ...props }) => <h1 style={{ fontSize: '32px', fontWeight: 800, marginBottom: '24px', letterSpacing: '-0.02em' }} {...props} />,
                                                    h2: ({ node, ...props }) => <h2 style={{ fontSize: '24px', fontWeight: 700, margin: '32px 0 16px', borderBottom: '1px solid #e5e7eb', paddingBottom: '8px' }} {...props} />,
                                                    h3: ({ node, ...props }) => <h3 style={{ fontSize: '18px', fontWeight: 600, margin: '24px 0 12px' }} {...props} />,
                                                    p: ({ node, ...props }) => <p style={{ fontSize: '15px', lineHeight: '1.6', color: '#374151', marginBottom: '16px' }} {...props} />,
                                                    pre: ({ node, ...props }) => <pre style={{ background: '#1e293b', color: '#f8fafc', padding: '16px', borderRadius: '8px', fontSize: '13px', overflow: 'auto', margin: '16px 0', fontFamily: 'Menlo, Monaco, Consolas, monospace' }} {...props} />,
                                                    code: ({ node, className, children, ...props }) => {
                                                        const match = /language-(\w+)/.exec(className || '');
                                                        const isBlock = match || String(children).includes('\n');
                                                        return isBlock ? (
                                                            <code className={className} {...props}>{children}</code>
                                                        ) : (
                                                            <code style={{ background: '#f1f5f9', padding: '2px 4px', borderRadius: '4px', fontSize: '13px', color: '#e11d48' }} className={className} {...props}>{children}</code>
                                                        );
                                                    },
                                                    ul: ({ node, ...props }) => <ul style={{ marginBottom: '16px', paddingLeft: '24px' }} {...props} />,
                                                    li: ({ node, ...props }) => <li style={{ marginBottom: '8px', fontSize: '15px', color: '#374151' }} {...props} />
                                                }}
                                            >
                                                {body}
                                            </ReactMarkdown>
                                        </>
                                    );
                                })()}
                            </div>
                        </div>

                        {/* 3. File Explorer (Right Panel) */}
                        <div style={{ width: '280px', borderLeft: '1px solid #e5e7eb', background: '#f8fafc', overflowY: 'auto', padding: '20px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', fontSize: '12px', fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                <List size={14} />
                                <span>Resources</span>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                {skillFiles.length > 0 ? (
                                    <FileTree
                                        files={skillFiles}
                                        selectedFile={selectedFile}
                                        onSelect={handleSelectFile}
                                    />
                                ) : (
                                    <div style={{ fontSize: '12px', color: '#9ca3af', fontStyle: 'italic', padding: '0 12px' }}>No resources found</div>
                                )}
                            </div>
                        </div>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', overflow: 'hidden' }}>
                        <div style={{ flex: 1, overflowY: 'auto' }}>
                            <div style={{ maxWidth: '800px', margin: '0 auto', padding: '40px 24px', display: 'flex', flexDirection: 'column', gap: '32px' }}>
                                {/* Search Bar Area */}
                                <div style={{ display: 'flex', gap: '0' }}>
                                    <div style={{ flex: 1, position: 'relative' }}>
                                        <Search size={18} style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#9ca3af', zIndex: 10 }} />
                                        <input
                                            className="input-field"
                                            style={{
                                                paddingLeft: '44px',
                                                height: '48px',
                                                fontSize: '14px',
                                                borderRadius: '8px 0 0 8px',
                                                border: '1px solid #111827',
                                                borderRight: 'none',
                                                background: 'white',
                                                width: '100%',
                                                boxSizing: 'border-box',
                                                outline: 'none',
                                                display: 'block'
                                            }}
                                            placeholder="Search skills (e.g. browser, github, automation)..."
                                            value={marketQuery}
                                            onChange={e => setMarketQuery(e.target.value)}
                                            onKeyDown={e => e.key === 'Enter' && searchMarket()}
                                        />
                                    </div>
                                    <button
                                        className="btn btn-primary"
                                        style={{
                                            padding: '0 24px',
                                            height: '48px',
                                            borderRadius: '0 8px 8px 0',
                                            fontSize: '14px',
                                            fontWeight: 600,
                                            border: '1px solid #111827',
                                            borderLeft: 'none',
                                            boxSizing: 'border-box',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            minWidth: '100px',
                                            flexShrink: 0
                                        }}
                                        onClick={searchMarket}
                                    >
                                        {isSearching ? 'Searching...' : 'Search'}
                                    </button>
                                </div>

                                {/* Marketplace Content */}
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                    {marketResults.length > 0 && (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', color: '#111827', flexShrink: 0 }}>
                                            <div style={{ width: '4px', height: '16px', background: '#111827', borderRadius: '2px' }}></div>
                                            <h2 style={{ fontSize: '14px', fontWeight: 700, margin: 0, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                                {marketQuery ? 'Search Results' : 'Popular Skills'}
                                            </h2>
                                        </div>
                                    )}

                                    {marketResults.length > 0 ? (
                                        marketResults.map(res => (
                                            <div
                                                key={res.full_name}
                                                className="card"
                                                style={{
                                                    padding: '16px 20px',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'space-between',
                                                    gap: '24px',
                                                    border: '1px solid #e5e7eb',
                                                    background: 'white',
                                                    borderRadius: '12px',
                                                    flexShrink: 0
                                                }}
                                            >
                                                <div style={{ flex: 1, minWidth: 0 }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                                                        <div style={{ fontWeight: 700, fontSize: '15px', color: '#111827' }}>{res.name}</div>
                                                        <div style={{ background: '#f1f5f9', color: '#475569', padding: '2px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 700 }}>SKILL</div>
                                                    </div>
                                                    <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>by {res.author}</div>
                                                    {res.description && (
                                                        <p style={{ fontSize: '13.5px', color: '#4b5563', lineHeight: '1.5', margin: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                            {res.description}
                                                        </p>
                                                    )}
                                                </div>
                                                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', paddingLeft: '16px', borderLeft: '1px solid #f1f5f9' }}>
                                                    {skills.some(s => s.name === res.name) ? (
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#10b981', fontWeight: 700, fontSize: '13px', minWidth: '100px', justifyContent: 'center' }}>
                                                            <CheckCircle size={14} />
                                                            Installed
                                                        </div>
                                                    ) : (
                                                        <button
                                                            className="btn btn-primary"
                                                            style={{ height: '36px', padding: '0 16px', fontSize: '13px', fontWeight: 600, gap: '6px', minWidth: '100px', justifyContent: 'center' }}
                                                            onClick={() => installSkill(res.full_name)}
                                                            disabled={installingPkg === res.full_name}
                                                        >
                                                            {installingPkg === res.full_name ? 'Installing...' : <><Download size={14} /> Install</>}
                                                        </button>
                                                    )}
                                                    <a
                                                        href={res.url}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="btn"
                                                        style={{ padding: '0 10px', height: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                                                    >
                                                        <ExternalLink size={16} color="#64748b" />
                                                    </a>
                                                </div>
                                            </div>
                                        ))
                                    ) : !isSearching ? (
                                        <div style={{ textAlign: 'center', padding: '80px 0', color: '#6b7280' }}>
                                            <Package size={48} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                                            <div style={{ fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>Skill Marketplace unavailable</div>
                                            <p style={{ fontSize: '14px', marginTop: '8px' }}>Store and search APIs are being updated by the team.</p>
                                        </div>
                                    ) : null}
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
            <InstallationModal />
        </div>
    );
}
