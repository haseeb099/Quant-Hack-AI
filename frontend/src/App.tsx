import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { AgentsPage } from "@/pages/AgentsPage";
import { DecisionsPage } from "@/pages/DecisionsPage";
import { MarketPage } from "@/pages/MarketPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { PositionsPage } from "@/pages/PositionsPage";
import { RiskPage } from "@/pages/RiskPage";
import { TradesPage } from "@/pages/TradesPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 5_000,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route index element={<OverviewPage />} />
            <Route path="positions" element={<PositionsPage />} />
            <Route path="trades" element={<TradesPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="risk" element={<RiskPage />} />
            <Route path="market" element={<MarketPage />} />
            <Route path="decisions" element={<DecisionsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
