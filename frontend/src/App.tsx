import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LanguageProvider } from './context/LanguageContext';
import { ThemeProvider } from './context/ThemeContext';
import { SessionProvider } from './context/SessionContext';
import { AppLayout } from './components/layout/AppLayout';
import { PublicLayout } from './components/layout/PublicLayout';
import { LandingPage } from './pages/LandingPage';
import { SignInPage } from './pages/SignInPage';
import { RegisterPage } from './pages/RegisterPage';
import { VerifyEmailPage } from './pages/VerifyEmailPage';
import { ForgotPasswordPage } from './pages/ForgotPasswordPage';
import { ResetPasswordPage } from './pages/ResetPasswordPage';
import { VerificationPage } from './pages/VerificationPage';
import { AppealsPage } from './pages/AppealsPage';
import { MyReviewsPage } from './pages/MyReviewsPage';
import { ReviewDetailPage } from './pages/ReviewDetailPage';
import { ReviewEditPage } from './pages/ReviewEditPage';
import { NotificationsPage } from './pages/NotificationsPage';
import { GuestEntryPage } from './pages/GuestEntryPage';
import { OverviewPage } from './pages/OverviewPage';
import { DestinationsPage } from './pages/DestinationsPage';
import { DestinationDetailPage } from './pages/DestinationDetailPage';
import { PlannerPage } from './pages/PlannerPage';
import { OfflinePacksPage } from './pages/OfflinePacksPage';
import { SavedTripsPage } from './pages/SavedTripsPage';
import { ReviewsPage } from './pages/ReviewsPage';
import { HealthCheckPage } from './pages/HealthCheckPage';

export const App: React.FC = () => {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <SessionProvider>
          <BrowserRouter>
            <Routes>
              {/* Public entry: choose guest or sign in. It is an entry point, never a gate:
                  every app route below opens directly for guests (Execution.md rule 1). */}
              <Route element={<PublicLayout />}>
                <Route index element={<LandingPage />} />
                <Route path="guest" element={<GuestEntryPage />} />
                <Route path="login" element={<SignInPage />} />
                <Route path="register" element={<RegisterPage />} />
                <Route path="verify-email" element={<VerifyEmailPage />} />
                <Route path="forgot-password" element={<ForgotPasswordPage />} />
                <Route path="reset-password" element={<ResetPasswordPage />} />
              </Route>

              <Route element={<AppLayout />}>
                <Route path="overview" element={<OverviewPage />} />
                <Route path="destinations" element={<DestinationsPage />} />
                <Route path="destinations/:id" element={<DestinationDetailPage />} />
                <Route path="planner" element={<PlannerPage />} />
                <Route path="offline-packs" element={<OfflinePacksPage />} />
                <Route path="trips" element={<SavedTripsPage />} />
                <Route path="reviews" element={<ReviewsPage />} />
                <Route path="health" element={<HealthCheckPage />} />
                <Route path="account/verification" element={<VerificationPage />} />
                <Route path="account" element={<Navigate to="/account/reviews" replace />} />
                <Route path="account/reviews" element={<MyReviewsPage />} />
                <Route path="account/reviews/:id" element={<ReviewDetailPage />} />
                <Route path="account/reviews/:id/edit" element={<ReviewEditPage />} />
                <Route path="account/appeals" element={<AppealsPage />} />
                <Route path="account/notifications" element={<NotificationsPage />} />
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </SessionProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
};

export default App;
