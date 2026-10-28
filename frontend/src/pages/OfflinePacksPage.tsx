import React from 'react';
import { DownloadCloud } from 'lucide-react';
import { FeatureUnavailable } from '../components/common/FeatureUnavailable';

/** Offline packs (R12, R13). No service worker or IndexedDB store exists yet, so nothing is saved. */
export const OfflinePacksPage: React.FC = () => (
  <FeatureUnavailable
    icon={DownloadCloud}
    title={['অফলাইন প্যাক', 'Offline packs']}
    summary={[
      'অফলাইন প্যাক এখনো তৈরি হয়নি, তাই এই মুহূর্তে কোনো গাইড ডিভাইসে সংরক্ষিত হয় না। ইন্টারনেট ছাড়া দেখতে চাইলে প্রয়োজনীয় তথ্য ও জরুরি নম্বর আগে লিখে রাখুন।',
      'Offline packs are not built yet, so no guide is saved on your device at the moment. If you will be without internet, note down the details and emergency numbers you need beforehand.',
    ]}
    plannedPoints={[
      ['একটি গন্তব্যের গাইড, সতর্কতা ও জরুরি নম্বর ডাউনলোড', "Download a destination's guide, advisories and emergency numbers"],
      ['ইন্টারনেট ছাড়া খোলা যাবে; প্যাক কবে তৈরি ও কতদিন বৈধ তা দেখাবে', 'Open without internet, with the date the pack was made and how long it stays valid'],
      ['পুরনো সতর্কতা কখনো বর্তমান হিসেবে দেখাবে না', 'Out-of-date advisories are never shown as current'],
      ['প্রতিটি প্যাক আলাদাভাবে মোছা যাবে', 'Delete any pack at any time'],
    ]}
    task="R12, R13"
    alternatives={[
      { to: '/destinations', label: ['গন্তব্য গাইড দেখুন', 'Browse destination guides'] },
    ]}
  />
);
