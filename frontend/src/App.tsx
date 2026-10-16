import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type User } from "./api";
import AppShell from "./components/AppShell";
import BrandMark from "./components/BrandMark";
import AccountsPage from "./pages/AccountsPage";
import AdminUsersPage from "./pages/AdminUsersPage";
import DownloadsPage from "./pages/DownloadsPage";
import JobPage from "./pages/JobPage";
import JobsPage from "./pages/JobsPage";
import LibraryPage from "./pages/LibraryPage";
import LoginPage from "./pages/LoginPage";
import ProfilePage from "./pages/ProfilePage";
import RegisterPage from "./pages/RegisterPage";
import SettingsPage from "./pages/SettingsPage";
import StatsPage from "./pages/StatsPage";
import TransferPage from "./pages/TransferPage";

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
      <div className="grid min-h-dvh place-items-center bg-canvas">
        <div className="flex flex-col items-center gap-4 text-ink/45">
          <BrandMark />
          <p className="text-sm">正在确认登录状态</p>
        </div>
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onAuthenticated={onAuthenticated} />} />
      <Route path="/register" element={<RegisterPage onAuthenticated={onAuthenticated} />} />
      <Route
        path="/accounts"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <AccountsPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route
        path="/transfer"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <TransferPage user={user} />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route path="/share" element={<Navigate to="/transfer" replace />} />
      <Route
        path="/library"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <LibraryPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route
        path="/stats"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <StatsPage user={user} />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route
        path="/downloads"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <DownloadsPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route
        path="/jobs"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <JobsPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route
        path="/jobs/:id"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <JobPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
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
        path="/settings"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <SettingsPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route
        path="/profile"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <ProfilePage user={user} />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
      <Route path="/" element={<Navigate to={user ? "/accounts" : "/login"} replace />} />
    </Routes>
  );
}
