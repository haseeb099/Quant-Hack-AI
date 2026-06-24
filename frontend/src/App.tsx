import { lazy, Suspense } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Skeleton } from "@/components/ui/skeleton";

const OverviewPage = lazy(() =>
  import("@/pages/OverviewPage").then((m) => ({ default: m.OverviewPage })),
);
const PositionsPage = lazy(() =>
  import("@/pages/PositionsPage").then((m) => ({ default: m.PositionsPage })),
);
const TradesPage = lazy(() =>
  import("@/pages/TradesPage").then((m) => ({ default: m.TradesPage })),
);
const AgentsPage = lazy(() =>
  import("@/pages/AgentsPage").then((m) => ({ default: m.AgentsPage })),
);
const RiskPage = lazy(() =>
  import("@/pages/RiskPage").then((m) => ({ default: m.RiskPage })),
);
const MarketPage = lazy(() =>
  import("@/pages/MarketPage").then((m) => ({ default: m.MarketPage })),
);
const DecisionsPage = lazy(() =>
  import("@/pages/DecisionsPage").then((m) => ({ default: m.DecisionsPage })),
);
const DemoPage = lazy(() =>
  import("@/pages/DemoPage").then((m) => ({ default: m.DemoPage })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 5_000,
    },
  },
});

function PageFallback() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route element={<DashboardLayout />}>
              <Route index element={<OverviewPage />} />
              <Route path="positions" element={<PositionsPage />} />
              <Route path="trades" element={<TradesPage />} />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="risk" element={<RiskPage />} />
              <Route path="market" element={<MarketPage />} />
              <Route path="decisions" element={<DecisionsPage />} />
              <Route path="demo" element={<DemoPage />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
