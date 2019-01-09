import logging
from multiprocessing.pool import ThreadPool
from multiprocessing import Pool

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class YoutubeCrawler(object):

    def __init__(self, api_key_list, processes=10, thread=False):
        """
        Args:
            api_key_list (list): developer key list
            processes(int): the number of processes
            thread(bool): Thread use True instead of Process, default False

        """
        self.api_key_iter = iter(api_key_list)
        self.client = build("youtube", "v3", developerKey=next(self.api_key_iter))
        self.processes = processes
        self.thread = thread

    @staticmethod
    def _remove_empty_kwargs(**kwargs):

        good_kwargs = {}

        if kwargs is not None:

            for key, value in kwargs.items():
                if value:
                    good_kwargs[key] = value

        return good_kwargs

    def _response(self, resource, **kwargs):
        """
        Args:
            resource(str): youtube client method resource
            **kwargs: Arbitrary keyword arguments.

        Returns:
            dict: response in dictionary form

        """
        kwargs = self._remove_empty_kwargs(**kwargs)

        response = None

        while not response:

            try:

                if resource == 'channels':
                    response = self.client.channels().list(
                        **kwargs
                    ).execute()

                if resource == 'search':
                    response = self.client.search().list(
                        **kwargs
                    ).execute()

                if resource == 'videos':
                    response = self.client.videos().list(
                        **kwargs
                    ).execute()

                if resource == 'playlistitems':
                    response = self.client.playlistItems().list(
                        **kwargs
                    ).execute()

            except HttpError as e:
                logger.error("%s" % e)
                if e.resp.status == 403:
                    self.client = build("youtube", "v3", developerKey=next(self.api_key_iter))
                pass

        return response

    @staticmethod
    def _split_list(l, n):
        """
        Args:
            l(list): original list to be split
            n(int): split size

        Returns:
            list: n-sized list from list l

        """
        split_list = []

        for i in range(0, len(l), n):
            split_list.append(l[i:i + n])

        return split_list

    def channel_desc(self, id=None):
        """Channel description method

        Args:
            id(str): channel_id

        Returns:
            list: dictionary array

        Examples:
            >>> channel_description(id=channel_id)
            [{'title': channel_title,
            'ch_id': channel_id,
            'description': channel_description,
             'publisehdAt': channel_created_date}, ...]

        """
        responses = self._response('channels', part='snippet', id=id)

        desc_date_list = [{'title': response['snippet']['title'],
                           'ch_id': response['id'],
                           'description': response['snippet']['description'],
                           'publishedAt': response['snippet']['publishedAt'][:10],
                           'thumbnails': response['snippet']['thumbnails']}

                          for response in responses['items']]

        return desc_date_list

    def channel_countstats(self, id=None):
        """Channel count statistics method

        Args:
            id(str): channel_id

        Returns:
            list: dictionary array

        Examples:
            >>> channel_countstats(id=channel_id)
            [{'ch_id': str,
            'subscriberCount': int;None,
            'viewCount': int,
            'videoCount': int,
            'sub_view_ratio': float;None}, ...]

        """
        responses = self._response('channels', part='statistics', id=id)

        result_list = []

        for response in responses['items']:

            ch_id = response['id']

            statistics_response = response['statistics']

            if statistics_response['hiddenSubscriberCount'] is True:

                subscriber_count = None

                sub_view_ratio = None

            else:

                subscriber_count = int(statistics_response['subscriberCount'])
                try:
                    sub_view_ratio = view_count / subscriber_count
                except ZeroDivisionError:
                    sub_view_ratio = None

            view_count = int(statistics_response['viewCount'])
            video_count = int(statistics_response['videoCount'])

            result_list.append({'ch_id': ch_id, 'subscriberCount': subscriber_count,
                                'viewCount': view_count, 'videoCount': video_count,
                                'sub_view_ratio': sub_view_ratio})

        return result_list

    def _video_desc(self, ch_id, upload_id):
        """video description list given by an upload id

        Args:
            ch_id(str): channel_id
            upload_id(str): upload_id

        Returns:
            dict

        Examples:
            >>> _video_desc(ch_id, upload_id)
            {'ch_id': channel_id,
             'upload_id': upload_id,
             'video_info_list': [{'channelId': channel_id,
                                  'videoId': video_id,
                                  'title': video title,
                                  'description': video description,
                                  'publishedAt': video published time,
                                  'thumbnails': video thumbnail_urls}, ...]}

        """
        next_page_token = ''
        video_dict_list = []

        while True:

            response = self._response('playlistitems', playlistId=upload_id,
                                      part='snippet',
                                      maxResults=50,
                                      pageToken=next_page_token)

            video_dict = [{'channelId': item['snippet']['channelId'],
                           'videoId': item['snippet']['resourceId']['videoId'],
                           'title': item['snippet']['title'],
                           'description': item['snippet']['description'],
                           'publishedAt': item['snippet']['publishedAt'],
                           'thumbnails': item['snippet']['thumbnails']
                           }
                          for item in response['items']]

            video_dict_list.extend(video_dict)

            if 'nextPageToken' in response.keys():
                next_page_token = response['nextPageToken']

            else:

                return {
                    'ch_id': ch_id,
                    'upload_id': upload_id,
                    'video_info_list': video_dict_list
                }

    def channel_video_desc(self, id=None):
        """video description list given by channel ids

        channel ids => upload ids => MultiThreading => video description list by upload ids

        Args:
             id(str): channel_id

        Returns:
            list: dictionary array

        Examples:
            >>>channel_video_desc(id=channel_id)
            [{'ch_id': channel_id,
              'upload_id': upload_id,
              'video_info_list': [{'channelId': channel_id,
                                   'videoId': video_id,
                                   'title': video title,
                                   'description': video description,
                                   'publishedAt': video published time,
                                   'thumbnails': video thumbnail_urls
                                   }, ...]}, ...]
            
        """

        responses = self._response('channels', part='contentDetails', id=id)

        ch_uploads_id = [{'ch_id': item['id'],
                          'uploads_id': item['contentDetails']['relatedPlaylists']['uploads']}
                         for item in responses['items']]
        results = []

        pool = Pool(self.processes)

        if self.thread:
            pool = ThreadPool(self.processes)

        for ch_uploads in ch_uploads_id:
            upload_id = ch_uploads['uploads_id']
            ch_id = ch_uploads['ch_id']

            ready = pool.apply_async(self._video_desc,
                                     kwds={
                                         'ch_id': ch_id,
                                         'upload_id': upload_id
                                     })
            results.append(ready.get())

        return results

    def video_statistics(self, **kwargs):

        '''
        Returns video statistics by its respective id

        Args:
            **kwargs: Arbitrary keyword arguments

        Returns:
            dictionary array: [{'videoId':id_video, 'statistics': video_statistics}, ..]
        '''

        responses = self._response('videos', **kwargs)

        items = responses['items']

        video_statistics_list = []

        for item in items:
            id_video = item['id']
            video_statistics = item['statistics']
            video_statistics_list.append({'videoId': id_video,
                                          'statistics': video_statistics})
        return video_statistics_list

    def _id_to_stats(self, x):

        id_join = ','.join(x)

        videos_stats = self.video_statistics(id=id_join, part='statistics')

        return videos_stats

    def video_statistics_by_channel(self, **kwargs):

        responses = self.channel_video_desc(**kwargs)

        ch_video_dict_array = []
        for response in responses:
            ch_video_dict = {}
            ch_id = response['ch_id']
            video_ids = [item['videoId'] for item in response['video_info_list']]
            ch_video_dict['ch_id'] = ch_id
            ch_video_dict['video_id'] = video_ids
            ch_video_dict_array.append(ch_video_dict)

        ch_video_info_array = []

        pool = Pool(self.processes)

        if self.thread:
            pool = ThreadPool(self.processes)

        for ch_video_dict in ch_video_dict_array:
            ch_id = ch_video_dict['ch_id']
            video_split_list = self._split_list(ch_video_dict['video_id'], 50)

            results = [pool.apply_async(self._id_to_stats, args=([split])).get()
                       for split in video_split_list]

            ch_videos_stats = {}
            ch_videos_stats['ch_id'] = ch_id
            ch_videos_stats['video_stats'] = results

            ch_video_info_array.append(ch_videos_stats)

        return ch_video_info_array

    def statistics_sum(self, *args):

        '''
        Returns the sum of values from video statistics dictionary array

        Args:
            *args: Arbitrary keyword arguments
            Dictionary array with key named 'statistics' and its value in dictionary

        Returns:

            dict: the sum of statistics

        '''

        vsc_sum = {}

        for vs in vsc:

            vs_stat = vs['statistics']
            keys = vs_stat.keys()

            for key in keys:

                if vs['statistics'][key].isdigit():

                    if key in vsc_sum.keys():

                        vsc_sum[key] += int(vs['statistics'][key])

                    else:
                        vsc_sum[key] = int(vs['statistics'][key])

        old_keys = [key for key in vsc_sum.keys()]

        for key in old_keys:
            vsc_sum[key + '_sum'] = vsc_sum[key]
            vsc_sum.pop(key)

        return vsc_sum
