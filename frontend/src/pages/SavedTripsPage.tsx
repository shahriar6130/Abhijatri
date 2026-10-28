import React from 'react';
import { Bookmark } from 'lucide-react';
import { FeatureUnavailable } from '../components/common/FeatureUnavailable';

/** Saved trip briefs (E09). They come from cost estimates (E08), which do not exist yet. */
export const SavedTripsPage: React.FC = () => (
  <FeatureUnavailable
    icon={Bookmark}
    title={['সংরক্ষিত ভ্রমণ', 'Saved trips']}
    summary={[
      'ভ্রমণ সংক্ষেপ খরচ পরিকল্পনা থেকে তৈরি হয়। খরচ পরিকল্পনা চালু হলে এখানে সংরক্ষণ করা যাবে।',
      'Trip briefs are created from the cost planner. Once the planner is available, you can save them here.',
    ]}
    plannedPoints={[
      ['খরচের হিসাব, নোট ও প্রয়োজনীয় যোগাযোগ একসাথে', 'An estimate with your notes and useful contacts in one place'],
      ['অনলাইন ও অফলাইনে খোলা, কপি ও মোছা', 'Open, copy and delete online and offline'],
    ]}
    task="E09"
    alternatives={[
      { to: '/destinations', label: ['গন্তব্য গাইড দেখুন', 'Browse destination guides'] },
      { to: '/reviews', label: ['রিভিউ লিখুন', 'Write a review'] },
    ]}
  />
);
