import { Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ClusterProvider } from "./ClusterContext";
import { HostsPage } from "./pages/HostsPage";
import { NodesPage } from "./pages/NodesPage";
import { JobsPage } from "./pages/JobsPage";
import { PartitionsPage } from "./pages/PartitionsPage";
import { ReservationsPage } from "./pages/ReservationsPage";
import { AccountsPage } from "./pages/AccountsPage";
import { AccountingPage } from "./pages/AccountingPage";
import { FairsharePage } from "./pages/FairsharePage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { ClusterPage } from "./pages/ClusterPage";

export default function App() {
  return (
    <ClusterProvider>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/nodes" replace />} />
          <Route path="hosts"        element={<HostsPage />} />
          <Route path="nodes"        element={<NodesPage />} />
          <Route path="jobs"         element={<JobsPage />} />
          <Route path="partitions"   element={<PartitionsPage />} />
          <Route path="reservations" element={<ReservationsPage />} />
          <Route path="accounts"     element={<AccountsPage />} />
          <Route path="accounting"   element={<AccountingPage />} />
          <Route path="fairshare"    element={<FairsharePage />} />
          <Route path="diagnostics"  element={<DiagnosticsPage />} />
          <Route path="cluster"      element={<ClusterPage />} />
          <Route path="*" element={<Navigate to="/nodes" replace />} />
        </Route>
      </Routes>
    </ClusterProvider>
  );
}
