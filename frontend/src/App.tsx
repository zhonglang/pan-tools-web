import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type User } from "./api";
import AppShell from "./components/AppShell";
import AdminUsersPage from "./pages/AdminUsersPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  function onAuthenticated(next: User) {
    setUser(next);
  }

  async function onLogout() {
    await api.logout();
    setUser(null);
    navigate("/login");
  }

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-canvas text-sm text-ink/60">正在确认登录状态</div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onAuthenticated={onAuthenticated} />} />
      <Route path="/register" element={<RegisterPage onAuthenticated={onAuthenticated} />} />
      <Route
        path="/admin/users"
        element={
          user?.role === "admin" ? (
            <AppShell user={user} onLogout={onLogout}>
              <AdminUsersPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route
        path="/"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <HomePage user={user} />
            </AppShell>
          ) : (
            <HomePage user={null} />
          )
        }
      />
    </Routes>
  );
}
