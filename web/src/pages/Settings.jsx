import { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Database, Folder, Shield, Cpu, ChevronRight, Box, Brain } from 'lucide-react';
import LoadingView from '../components/LoadingView';

const ConfigSection = ({ title, icon: Icon, children, id }) => (
    <div id={id} style={{ background: 'white', borderRadius: '8px', border: '1px solid #e5e7eb', overflow: 'hidden', marginBottom: '16px' }}>
        <div style={{ padding: '10px 16px', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'center', gap: '8px', background: '#f9fafb' }}>
            <Icon size={16} color="#374151" />
            <h2 style={{ fontSize: '14px', fontWeight: 700, color: '#111827' }}>{title}</h2>
        </div>
        <div style={{ padding: '12px 16px' }}>
            {children}
        </div>
    </div>
);

const ConfigItem = ({ label, value, isCode = false }) => (
    <div style={{ display: 'flex', borderBottom: '1px solid #f3f4f6', padding: '8px 0', lastChild: { borderBottom: 'none' } }}>
        <div style={{ width: '160px', fontSize: '12px', fontWeight: 600, color: '#6b7280' }}>{label}</div>
        <div style={{ flex: 1, fontSize: '12px', color: '#111827', fontFamily: isCode ? 'monospace' : 'inherit', wordBreak: 'break-all' }}>
            {Array.isArray(value) ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    {value.map((v, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <ChevronRight size={10} color="#9ca3af" />
                            <span>{v}</span>
                        </div>
                    ))}
                </div>
            ) : (
                String(value)
            )}
        </div>
    </div>
);

export default function Settings() {
    const [config, setConfig] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeSection, setActiveSection] = useState('models');

    useEffect(() => {
        fetch('/api/config')
            .then(res => res.json())
            .then(data => {
                setConfig(data);
                setLoading(false);
            })
            .catch(err => {
                console.error('Failed to fetch config:', err);
                setLoading(false);
            });
    }, []);

    const scrollToSection = (id) => {
        const element = document.getElementById(id);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth' });
            setActiveSection(id);
        }
    };

    if (loading) return <LoadingView message="Loading Settings..." fullScreen={false} />;
    if (!config) return <div style={{ padding: '24px', color: '#ef4444' }}>Error loading settings</div>;

    const navItems = [
        { id: 'models', label: 'Models', icon: Cpu },
        { id: 'paths', label: 'Paths', icon: Folder },
        { id: 'runtime', label: 'Runtime', icon: Database },
        { id: 'channels', label: 'Channels', icon: SettingsIcon },
        { id: 'features', label: 'Features', icon: SettingsIcon },
        { id: 'sandbox', label: 'Sandbox', icon: Box },
        { id: 'memory', label: 'Memory', icon: Brain },
        { id: 'security', label: 'Security', icon: Shield },
        { id: 'tracing', label: 'Tracing', icon: SettingsIcon },
    ];

    return (
        <div style={{ flex: 1, background: '#f9fafb', height: '100vh', display: 'flex' }}>
            {/* Quick Navigation Sidebar - Slimmer */}
            <div style={{
                width: '180px',
                padding: '24px 12px',
                borderRight: '1px solid #e5e7eb',
                background: 'white',
                position: 'sticky',
                top: 0,
                height: '100vh'
            }}>
                <div style={{ padding: '0 8px', marginBottom: '24px' }}>
                    <h1 style={{ fontSize: '16px', fontWeight: 700, color: '#111827', marginBottom: '2px' }}>Settings</h1>
                    <p style={{ color: '#6b7280', fontSize: '11px' }}>System configuration</p>
                </div>

                <nav>
                    {navItems.map((item) => {
                        const Icon = item.icon;
                        const isActive = activeSection === item.id;
                        return (
                            <button
                                key={item.id}
                                onClick={() => scrollToSection(item.id)}
                                style={{
                                    width: '100%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '10px',
                                    padding: '8px 10px',
                                    borderRadius: '6px',
                                    border: 'none',
                                    background: isActive ? '#f3f4f6' : 'transparent',
                                    color: isActive ? '#111827' : '#6b7280',
                                    fontWeight: isActive ? 600 : 500,
                                    fontSize: '13px',
                                    textAlign: 'left',
                                    cursor: 'pointer',
                                    transition: 'all 0.15s',
                                    marginBottom: '2px'
                                }}
                            >
                                <Icon size={16} />
                                <span>{item.label}</span>
                            </button>
                        );
                    })}
                </nav>
            </div>

            {/* Main Content Area - More Compact */}
            <div style={{ flex: 1, padding: '24px 32px', overflowY: 'auto' }}>
                <div style={{ maxWidth: '900px' }}>
                    {/* Model Configurations - Compact Cards */}
                    <ConfigSection title="Model Mappings" icon={Cpu} id="models">
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
                            {Object.entries(config.model_mappings || {}).map(([kind, mapping]) => (
                                <div key={kind} style={{ border: '1px solid #f3f4f6', borderRadius: '6px', padding: '12px', background: '#ffffff' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', borderBottom: '1px solid #f3f4f6', pb: '4px' }}>
                                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#111827', textTransform: 'uppercase' }}>{kind}</span>
                                        <span style={{ fontSize: '11px', color: '#3b82f6', fontWeight: 600 }}>{mapping.model_id}</span>
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                                            <span style={{ color: '#6b7280' }}>Tokens / Temp</span>
                                            <span style={{ color: '#111827', fontWeight: 500 }}>{mapping.max_tokens} / {mapping.temperature}</span>
                                        </div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                                            <span style={{ color: '#6b7280' }}>Tools</span>
                                            <span style={{ color: mapping.supports_tools ? '#10b981' : '#f59e0b', fontWeight: 600 }}>{mapping.supports_tools ? 'Yes' : 'No'}</span>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </ConfigSection>

                    {/* System Paths */}
                    <ConfigSection title="System Paths" icon={Folder} id="paths">
                        <ConfigItem label="Skills Dirs" value={config.skills_dirs} isCode />
                        <ConfigItem label="Tools Dirs" value={config.tools_dirs} isCode />
                        <ConfigItem label="Agents Path" value={config.agents_dir} isCode />
                        <ConfigItem label="Project Context Dirs" value={config.context?.project_context_dirs || []} isCode />
                    </ConfigSection>

                    {/* Runtime Storage */}
                    <ConfigSection title="Runtime Storage" icon={Database} id="runtime">
                        <ConfigItem label="Sessions Dir" value={config.sessions_dir} isCode />
                        <div style={{ display: 'flex', borderBottom: '1px solid #f3f4f6', padding: '8px 0' }}>
                            <div style={{ width: '160px', fontSize: '12px', fontWeight: 600, color: '#6b7280' }}>Storage</div>
                            <div style={{ flex: 1, fontSize: '12px', color: '#111827' }}>
                                <div style={{ background: '#f8fafc', padding: '8px', borderRadius: '4px', border: '1px solid #e5e7eb' }}>
                                    <div style={{ marginBottom: '4px' }}>Type: <code style={{ color: '#0369a1' }}>{config.storage?.type || 'local'}</code></div>
                                    {config.storage?.type === 's3' && (
                                        <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                            <div>Bucket: {config.storage.s3_bucket}</div>
                                            <div>Prefix: {config.storage.s3_prefix}</div>
                                            <div>Region: {config.storage.s3_region}</div>
                                            {config.storage.s3_endpoint_url && <div>Endpoint: {config.storage.s3_endpoint_url}</div>}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </ConfigSection>

                    {/* Channels */}
                    <ConfigSection title="Active Channels" icon={SettingsIcon} id="channels">
                        {Object.entries(config.channels || {}).map(([name, ch]) => (
                            <div key={name} style={{ border: '1px solid #f3f4f6', borderRadius: '6px', padding: '12px', background: '#ffffff', marginBottom: '8px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#111827', textTransform: 'uppercase' }}>
                                        {name} ({ch.type})
                                    </div>
                                    <div style={{ fontSize: '11px', color: '#3b82f6', fontWeight: 600 }}>{ch.bot_name || 'Agent'}</div>
                                </div>
                                <div style={{ fontSize: '11px', color: '#6b7280', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                    <div>Chat ID: {ch.chat_id || 'N/A'}</div>
                                    {ch.domain && <div>Domain: <span style={{ fontFamily: 'monospace' }}>{ch.domain}</span></div>}
                                    {ch.url && <div style={{ wordBreak: 'break-all' }}>URL: {ch.url}</div>}
                                </div>
                            </div>
                        ))}
                        {(!config.channels || Object.keys(config.channels).length === 0) && <div style={{ fontSize: '12px', color: '#6b7280' }}>No external channels configured</div>}
                    </ConfigSection>

                    {/* Features section (Web & Daemon) */}
                    <ConfigSection title="Features" icon={SettingsIcon} id="features">
                        <div style={{ marginBottom: '16px' }}>
                            <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '8px' }}>Web Interface</div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: config.web?.enabled ? '#10b981' : '#ef4444' }}></div>
                                <span style={{ fontSize: '13px', fontWeight: 600, color: '#111827' }}>{config.web?.enabled ? 'Enabled' : 'Disabled'}</span>
                            </div>
                        </div>
                        <div>
                            <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '8px' }}>Daemon</div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: config.daemon?.enabled ? '#10b981' : '#ef4444' }}></div>
                                <span style={{ fontSize: '13px', fontWeight: 600, color: '#111827' }}>{config.daemon?.enabled ? 'Enabled' : 'Disabled'}</span>
                            </div>
                            {config.daemon?.enabled && (
                                <div style={{ background: '#f8fafc', padding: '12px', borderRadius: '8px', border: '1px solid #e5e7eb', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <div>
                                        <div style={{ fontSize: '10px', color: '#64748b', fontWeight: 700 }}>WATCH INTERVAL</div>
                                        <div style={{ fontSize: '12px', color: '#111827' }}>{config.daemon.watch_interval}s</div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '10px', color: '#64748b', fontWeight: 700 }}>MAX LOOPS</div>
                                        <div style={{ fontSize: '12px', color: '#111827' }}>{config.daemon.max_concurrent_loops}</div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '10px', color: '#64748b', fontWeight: 700 }}>GRACEFUL TIMEOUT</div>
                                        <div style={{ fontSize: '12px', color: '#111827' }}>{config.daemon.graceful_stop_timeout}s</div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </ConfigSection>

                    {/* Sandbox */}
                    <ConfigSection title="Sandbox Environment" icon={Box} id="sandbox">
                        <ConfigItem label="Enabled" value={config.sandbox?.enabled ? 'Yes' : 'No'} />
                        {config.sandbox?.enabled && (
                            <>
                                <ConfigItem label="Type" value={config.sandbox.type} isCode />
                                <ConfigItem label="Idle Timeout" value={`${config.sandbox.idle_timeout}s`} />
                                <ConfigItem label="Token TTL" value={`${config.sandbox.token_ttl}s`} />
                                {config.sandbox.type === 'docker' && config.sandbox?.docker && (
                                    <div style={{ background: '#f8fafc', padding: '12px', borderRadius: '8px', border: '1px solid #e5e7eb', marginTop: '12px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                                        <div>
                                            <div style={{ fontSize: '10px', color: '#64748b', fontWeight: 700 }}>IMAGE</div>
                                            <div style={{ fontSize: '12px', color: '#111827', fontFamily: 'monospace' }}>{config.sandbox.docker.image}</div>
                                        </div>
                                        <div>
                                            <div style={{ fontSize: '10px', color: '#64748b', fontWeight: 700 }}>MEMORY LIMIT</div>
                                            <div style={{ fontSize: '12px', color: '#111827' }}>{config.sandbox.docker.memory_limit}</div>
                                        </div>
                                        <div>
                                            <div style={{ fontSize: '10px', color: '#64748b', fontWeight: 700 }}>CPU LIMIT</div>
                                            <div style={{ fontSize: '12px', color: '#111827' }}>{config.sandbox.docker.cpu_limit}</div>
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </ConfigSection>

                    {/* Memory */}
                    <ConfigSection title="Memory" icon={Brain} id="memory">
                        <ConfigItem label="Enabled" value={config.memory?.enabled ? 'Yes' : 'No'} />
                        {config.memory?.enabled && (
                            <>
                                <ConfigItem label="Vector Store" value={config.memory.vector_store} isCode />
                                <ConfigItem label="Store Path" value={config.memory.vector_store_path} isCode />
                                <ConfigItem label="LLM Model" value={config.memory.llm_model_kind} isCode />
                                <ConfigItem label="Embedding Model" value={config.memory.embedding_model_kind} isCode />
                                <ConfigItem label="Search Top K" value={config.memory.search_top_k} />
                                <ConfigItem label="Search Threshold" value={config.memory.search_threshold} />
                            </>
                        )}
                    </ConfigSection>

                    {/* Security & Permissions */}
                    <ConfigSection title="Security & Permissions" icon={Shield} id="security">
                        <ConfigItem label="Auth Enabled" value={config.auth?.enabled ? 'Yes' : 'No'} />
                        {config.auth?.enabled && (
                            <>
                                <ConfigItem label="Auth Providers" value={config.auth.providers?.map(p => p.type) || []} isCode />
                                <ConfigItem label="Allowed Emails" value={config.auth.allowed_emails || []} isCode />
                                <ConfigItem label="Public Routes" value={config.auth.public_routes || []} isCode />
                            </>
                        )}
                        <div style={{ marginTop: '16px', marginBottom: '8px', fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
                            Permission Rules
                        </div>
                        <ConfigItem label="Allow Rules" value={config.permissions?.allow?.length > 0 ? config.permissions.allow : ['None']} isCode />
                        <ConfigItem label="Deny Rules" value={config.permissions?.deny?.length > 0 ? config.permissions.deny : ['None']} isCode />
                    </ConfigSection>

                    {/* Tracing Configuration */}
                    <ConfigSection title="Tracing Configuration" icon={SettingsIcon} id="tracing">
                        {(config.tracers || []).map((t, i) => (
                            <ConfigItem key={i} label={`Backend ${i + 1}`} value={`${t.type}${t.otlp_endpoint ? ` (${t.otlp_endpoint})` : ''}`} isCode />
                        ))}
                    </ConfigSection>
                </div>
            </div>
        </div>
    );
}
