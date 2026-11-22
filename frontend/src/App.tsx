import React, { lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { LanguageProvider } from './context/LanguageContext';
import { ThemeProvider } from './context/ThemeContext';
import { SessionProvider } from './context/SessionContext';
import { UpdatePrompt } from './components/common/UpdatePrompt';
import { useReconnectPackCheck } from './hooks/useOfflinePacks';
import { AppLayout } from './components/layout/AppLayout';
import { PublicLayout } from './components/layout/PublicLayout';
import { LandingPage } from './pages/LandingPage';
import { GuestEntryPage } from './pages/GuestEntryPage';
import { OverviewPage } from './pages/OverviewPage';
import { DestinationsPage } from './pages/DestinationsPage';
import { DestinationDetailPage } from './pages/DestinationDetailPage';

/*
 * Code splitting (Frontend-Implemented 5i): the landing, guest entry, overview and destination pages
 * are in the first download; every other page loads when first opened. The service worker precaches
 * all of them in the background, so later visits and offline use do not wait.
 */
const page = <K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })));
const SignInPage = page(() => import('./pages/SignInPage'), 'SignInPage');
const PrivacyPage = page(() => import('./pages/PrivacyPage'), 'PrivacyPage');
const RegisterPage = page(() => import('./pages/RegisterPage'), 'RegisterPage');
const VerifyEmailPage = page(() => import('./pages/VerifyEmailPage'), 'VerifyEmailPage');
const ForgotPasswordPage = page(() => import('./pages/ForgotPasswordPage'), 'ForgotPasswordPage');
const ResetPasswordPage = page(() => import('./pages/ResetPasswordPage'), 'ResetPasswordPage');
const VerificationPage = page(() => import('./pages/VerificationPage'), 'VerificationPage');
const ToursPage = page(() => import('./pages/ToursPage'), 'ToursPage');
const FindToursPage = page(() => import('./pages/ToursPage'), 'FindToursPage');
const CreateTourPage = page(() => import('./pages/ToursPage'), 'CreateTourPage');
const TourDetailPage = page(() => import('./pages/ToursPage'), 'TourDetailPage');
const TourCodePage = page(() => import('./pages/ToursPage'), 'TourCodePage');
const TourPreferencesPage = page(() => import('./pages/ToursPage'), 'TourPreferencesPage');
const FindPeoplePage = page(() => import('./pages/ToursPage'), 'FindPeoplePage');
const TourRequestsPage = page(() => import('./pages/ToursPage'), 'TourRequestsPage');
const TourInvitationsPage = page(() => import('./pages/ToursPage'), 'TourInvitationsPage');
const AppealsPage = page(() => import('./pages/AppealsPage'), 'AppealsPage');
const MyReportsPage = page(() => import('./pages/MyReportsPage'), 'MyReportsPage');
const MyReviewsPage = page(() => import('./pages/MyReviewsPage'), 'MyReviewsPage');
const ReviewDetailPage = page(() => import('./pages/ReviewDetailPage'), 'ReviewDetailPage');
const ReviewEditPage = page(() => import('./pages/ReviewEditPage'), 'ReviewEditPage');
const NotificationsPage = page(() => import('./pages/NotificationsPage'), 'NotificationsPage');
const PlannerPage = page(() => import('./pages/PlannerPage'), 'PlannerPage');
const OfflinePacksPage = page(() => import('./pages/OfflinePacksPage'), 'OfflinePacksPage');
const SavedTripsPage = page(() => import('./pages/SavedTripsPage'), 'SavedTripsPage');
const HealthCheckPage = page(() => import('./pages/HealthCheckPage'), 'HealthCheckPage');
const WriteReviewPage = page(() => import('./pages/ReviewsPage'), 'WriteReviewPage');
const ReviewReceiptPage = page(() => import('./pages/ReviewsPage'), 'ReviewReceiptPage');

/** Checks downloaded packs whenever the connection returns (R13, Offline-Frontend-Guideline 5.3). */
const PackReconnect: React.FC = () => {
  useReconnectPackCheck();
  return null;
};

/** Old `/reviews` links (including `?destination=`) open the writing page. */
const ReviewsRedirect: React.FC = () => {
  const { search } = useLocation();
  return <Navigate to={`/reviews/write${search}`} replace />;
};

export const App: React.FC = () => {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <SessionProvider>
          <UpdatePrompt />
          <PackReconnect />
          <BrowserRouter>
            <Routes>
              {/* Public entry: choose guest or sign in. It is an entry point, never a gate:
                  every app route below opens directly for guests (Execution.md rule 1). */}
              <Route element={<PublicLayout />}>
                <Route index element={<LandingPage />} />
                <Route path="guest" element={<GuestEntryPage />} />
                <Route path="privacy" element={<PrivacyPage />} />
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
                <Route path="reviews" element={<ReviewsRedirect />} />
                <Route path="reviews/write" element={<WriteReviewPage />} />
                <Route path="reviews/receipt" element={<ReviewReceiptPage />} />
                <Route path="health" element={<HealthCheckPage />} />
                <Route path="verify" element={<VerificationPage />} />
                <Route path="verify/status" element={<VerificationPage />} />
                <Route path="account/verification" element={<Navigate to="/verify" replace />} />
                <Route path="tours" element={<ToursPage />} />
                <Route path="tours/find" element={<FindToursPage />} />
                <Route path="tours/find/people" element={<FindPeoplePage />} />
                <Route path="tours/new" element={<CreateTourPage />} />
                <Route path="tours/preferences" element={<TourPreferencesPage />} />
                <Route path="tours/requests" element={<TourRequestsPage />} />
                <Route path="tours/invitations" element={<TourInvitationsPage />} />
                <Route path="tours/:publicId" element={<TourDetailPage />} />
                <Route path="tours/:publicId/:tab" element={<TourDetailPage />} />
                <Route path="t/:code" element={<TourCodePage />} />
                <Route path="account" element={<Navigate to="/account/reviews" replace />} />
                <Route path="account/reviews" element={<MyReviewsPage />} />
                <Route path="account/reviews/:id" element={<ReviewDetailPage />} />
                <Route path="account/reviews/:id/edit" element={<ReviewEditPage />} />
                <Route path="account/appeals" element={<AppealsPage />} />
                <Route path="account/reports" element={<MyReportsPage />} />
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
