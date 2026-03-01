import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import AgentStore from './pages/AgentStore';
import AgentEditor from './pages/AgentEditor';
import SkillStore from './pages/SkillStore';
import ToolStore from './pages/ToolStore';
import ToolEditor from './pages/ToolEditor';
import SessionStore from './pages/SessionStore';
import Settings from './pages/Settings';
import Tracing from './pages/Tracing';
import MCP from './pages/MCP';
import Knowledge from './pages/Knowledge';
import Memory from './pages/Memory';

// Global fetch interceptor — redirects to /auth/login on 401.
// Wraps the native fetch once so all API calls in the app are covered.
// Guards: skip redirect if already on /auth/login or if the request itself
// targets an /auth/* route, to prevent redirect loops.
const _originalFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const response = await _originalFetch(...args);
  if (response.status === 401) {
    const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url ?? '');
    const alreadyOnLogin = window.location.pathname === '/auth/login';
    const isAuthRoute = url.startsWith('/auth/');
    if (!alreadyOnLogin && !isAuthRoute) {
      window.location.href = '/auth/login';
    }
  }
  return response;
};

function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/agents" element={<AgentStore />} />
          <Route path="/agents/new" element={<AgentEditor />} />
          <Route path="/agents/:uuid" element={<AgentEditor />} />
          <Route path="/sessions/:sessionId?" element={<SessionStore />} />
          <Route path="/skills" element={<SkillStore />} />
          <Route path="/tools" element={<ToolStore />} />
          <Route path="/tools/edit/:toolName" element={<ToolEditor />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/tracing" element={<Tracing />} />
          <Route path="/mcp" element={<MCP />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/memory" element={<Memory />} />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
