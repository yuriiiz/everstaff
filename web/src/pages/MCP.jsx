import { Construction, Box, Globe } from 'lucide-react';

export default function MCP() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#f9fafb' }}>
            <div style={{ padding: '0 24px', background: 'white', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', height: '60px', flexShrink: 0 }}>
                <div>
                    <h1 style={{ fontSize: '15px', fontWeight: 700, color: '#111827', margin: 0 }}>MCP (Model Context Protocol)</h1>
                </div>
            </div>

            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px' }}>
                <div style={{ textAlign: 'center', maxWidth: '500px' }}>
                    <div style={{
                        width: '80px',
                        height: '80px',
                        borderRadius: '24px',
                        background: '#f3f4f6',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        margin: '0 auto 24px',
                        color: '#111827'
                    }}>
                        <Construction size={40} />
                    </div>
                    <h2 style={{ fontSize: '24px', fontWeight: 800, color: '#111827', marginBottom: '12px', letterSpacing: '-0.025em' }}>Coming Soon</h2>
                    <p style={{ fontSize: '16px', color: '#6b7280', lineHeight: '1.6', margin: 0 }}>
                        MCP (Model Context Protocol) features are currently under development. Soon you will be able to manage and connect various MCP services to empower your agents with enhanced capabilities.
                    </p>
                    <div style={{ marginTop: '32px', display: 'flex', justifyContent: 'center', gap: '16px' }}>
                        <div style={{ padding: '12px 20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <Box size={18} color="#9ca3af" />
                            <span style={{ fontSize: '14px', fontWeight: 600, color: '#4b5563' }}>Resource Management</span>
                        </div>
                        <div style={{ padding: '12px 20px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <Globe size={18} color="#9ca3af" />
                            <span style={{ fontSize: '14px', fontWeight: 600, color: '#4b5563' }}>Remote Services</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
