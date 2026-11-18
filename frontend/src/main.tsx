import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Layout } from "@/components/Layout";
import { UserProvider, useUser } from "@/lib/user";
import ChatPage from "@/routes/Chat";
import InboxPage from "@/routes/Inbox";
import RequirementPage from "@/routes/Requirement";
import POPage from "@/routes/PurchaseOrder";
import BatchesPage from "@/routes/Batches";
import RunPage from "@/routes/Run";
import PolicyPage from "@/routes/Policy";
import AmendmentNewPage from "@/routes/AmendmentNew";
import AmendmentPage from "@/routes/Amendment";
import ContractsPage from "@/routes/Contracts";
import SuppliersPage from "@/routes/Suppliers";
import ComparePage from "@/routes/Compare";
import AuditPage from "@/routes/Audit";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function Home() {
  const { role } = useUser();
  return <Navigate to={role === "REQUESTER" ? "/chat" : role === "PROCUREMENT_ADMIN" ? "/policy" : "/inbox"} replace />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
    <QueryClientProvider client={qc}>
      <UserProvider>
        <BrowserRouter>
          <Layout>
            <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/requirements/:id" element={<RequirementPage />} />
              <Route path="/po/:id" element={<POPage />} />
              <Route path="/batches" element={<BatchesPage />} />
              <Route path="/batches/:id" element={<RunPage />} />
              <Route path="/policy" element={<PolicyPage />} />
              <Route path="/policy/amendments/new" element={<AmendmentNewPage />} />
              <Route path="/policy/amendments/:id" element={<AmendmentPage />} />
              <Route path="/contracts" element={<ContractsPage />} />
              <Route path="/suppliers" element={<SuppliersPage />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            </ErrorBoundary>
          </Layout>
        </BrowserRouter>
      </UserProvider>
    </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
